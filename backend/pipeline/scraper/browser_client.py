"""curl_cffi client for getting past the Gazette's Cloudflare TLS fingerprinting.

httpx/requests get blocked by JA3/JA4 checks; curl_cffi impersonates a real
Chrome TLS handshake so Cloudflare lets us through.
"""

import asyncio
import logging
import random

from curl_cffi.requests import AsyncSession
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

DEFAULT_DELAY = 5.0
DEFAULT_TIMEOUT = 30

# 429 backoff cycle (seconds) — loops until rate limit clears, resets per call.
_429_WAIT_CYCLE = [30, 35, 45, 60, 15]


class BrowserFetchError(Exception):
    """HTTP-level error from a curl_cffi response."""

    def __init__(self, status: int, url: str) -> None:
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} for {url}")


def _is_retryable_status(status: int) -> bool:
    return status >= 500


class CurlCffiClient:
    """Async HTTP client with a Chrome TLS fingerprint (no real browser needed).

    Usage::

        async with CurlCffiClient(delay=3.0) as client:
            html = await client.fetch("https://example.com")
    """

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        timeout: int = DEFAULT_TIMEOUT,
        proxy: str | None = None,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self._proxy = proxy
        self._session: AsyncSession | None = None
        self._last_request_time: float = 0.0

    async def __aenter__(self) -> "CurlCffiClient":
        kwargs: dict = {
            "impersonate": "chrome",
            "timeout": self.timeout,
        }
        if self._proxy:
            kwargs["proxy"] = self._proxy
        self._session = AsyncSession(**kwargs)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _rate_limit(self) -> None:
        """Min delay between requests, with ±50% jitter."""
        jittered_delay = self.delay * random.uniform(0.5, 1.5)
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < jittered_delay:
            await asyncio.sleep(jittered_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def fetch(self, url: str) -> str:
        """Fetch a URL as text. Rate-limited; retries on 429/5xx."""
        if self._session is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with CurlCffiClient()' context."
            )
        await self._rate_limit()
        return await self._fetch_with_retry(url)

    async def fetch_bytes(self, url: str) -> bytes:
        """Fetch raw bytes (PDFs etc). Rate-limited; retries on 429/5xx."""
        if self._session is None:
            raise RuntimeError(
                "Client not initialized. Use 'async with CurlCffiClient()' context."
            )
        await self._rate_limit()
        return await self._fetch_bytes_with_retry(url)

    # don't retry on 4xx other than 429 — those won't get better
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=(
            retry_if_exception(
                lambda e: isinstance(e, BrowserFetchError)
                and _is_retryable_status(e.status)
            )
            | retry_if_exception_type(ConnectionError)
        ),
        reraise=True,
    )
    async def _fetch_with_retry(self, url: str) -> str:
        """Tenacity handles 5xx/connection retries; 429 has its own loop below."""
        assert self._session is not None  # guaranteed by fetch()

        response = await self._session.get(url)
        status = response.status_code

        # 429: honor Retry-After, fall back to the wait cycle
        cycle_index = 0
        while status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                wait = int(retry_after) if retry_after is not None else None
            except ValueError:
                wait = None
            if wait is None:
                wait = _429_WAIT_CYCLE[cycle_index % len(_429_WAIT_CYCLE)]
            logger.warning("Rate limited (429) for %s, retrying in %ds", url, wait)
            await asyncio.sleep(wait)
            cycle_index += 1
            response = await self._session.get(url)
            status = response.status_code

        # raise on 5xx so tenacity does the exponential backoff
        if _is_retryable_status(status):
            logger.warning("HTTP %d for %s, will retry", status, url)
            raise BrowserFetchError(status, url)

        if status >= 400:
            raise BrowserFetchError(status, url)

        return response.text

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=(
            retry_if_exception(
                lambda e: isinstance(e, BrowserFetchError)
                and _is_retryable_status(e.status)
            )
            | retry_if_exception_type(ConnectionError)
        ),
        reraise=True,
    )
    async def _fetch_bytes_with_retry(self, url: str) -> bytes:
        """Bytes variant of _fetch_with_retry — same 429/5xx handling."""
        assert self._session is not None

        response = await self._session.get(url)
        status = response.status_code

        cycle_index = 0
        while status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                wait = int(retry_after) if retry_after is not None else None
            except ValueError:
                wait = None
            if wait is None:
                wait = _429_WAIT_CYCLE[cycle_index % len(_429_WAIT_CYCLE)]
            logger.warning("Rate limited (429) for %s, retrying in %ds", url, wait)
            await asyncio.sleep(wait)
            cycle_index += 1
            response = await self._session.get(url)
            status = response.status_code

        if _is_retryable_status(status):
            logger.warning("HTTP %d for %s, will retry", status, url)
            raise BrowserFetchError(status, url)

        if status >= 400:
            raise BrowserFetchError(status, url)

        return response.content
