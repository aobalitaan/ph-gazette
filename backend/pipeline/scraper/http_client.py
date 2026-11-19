"""Async HTTP client for polite web scraping of the Official Gazette."""

import asyncio
import logging
import random

import httpx
from tenacity import retry, retry_if_exception, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

DEFAULT_DELAY = 5.0
DEFAULT_TIMEOUT = 30.0

# 429 backoff cycle (seconds) — loops until rate limit clears, resets per call.
_429_WAIT_CYCLE = [30, 35, 45, 60, 15]

# One profile per worker so requests look like different devices.
_CHROME_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)
_FIREFOX_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
)
_CHROME_SEC_CH_UA = (
    '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"'
)

_BROWSER_PROFILES = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": _CHROME_ACCEPT,
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-CH-UA": _CHROME_SEC_CH_UA,
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": _CHROME_ACCEPT,
        "Accept-Language": "en-US,en;q=0.9,fil;q=0.8",
        "Sec-CH-UA": _CHROME_SEC_CH_UA,
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"macOS"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
            "Gecko/20100101 Firefox/133.0"
        ),
        "Accept": _FIREFOX_ACCEPT,
        "Accept-Language": "en-US,en;q=0.5",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": _CHROME_ACCEPT,
        "Accept-Language": "en-PH,en;q=0.9,fil;q=0.8",
        "Sec-CH-UA": _CHROME_SEC_CH_UA,
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Linux"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) "
            "Gecko/20100101 Firefox/133.0"
        ),
        "Accept": _FIREFOX_ACCEPT,
        "Accept-Language": "en-GB,en;q=0.5",
    },
]

_COMMON_HEADERS = {
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


class GazetteClient:
    """Async HTTP client with rate limiting and retries.

    One session (cookies + pool) per instance. For multiple workers, give each
    a distinct profile_id so they look like different browsers.
    """

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        timeout: float = DEFAULT_TIMEOUT,
        profile_id: int = 0,
        proxy: str | None = None,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.profile_id = profile_id
        self.proxy = proxy
        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0.0

    async def __aenter__(self) -> "GazetteClient":
        profile = _BROWSER_PROFILES[self.profile_id % len(_BROWSER_PROFILES)]
        headers = {**_COMMON_HEADERS, **profile}
        kwargs: dict = {
            "headers": headers,
            "follow_redirects": True,
            "timeout": httpx.Timeout(self.timeout),
        }
        if self.proxy:
            kwargs["proxy"] = self.proxy
        self._client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _rate_limit(self) -> None:
        """Min delay between requests, with ±50% jitter."""
        jittered_delay = self.delay * random.uniform(0.5, 1.5)
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < jittered_delay:
            await asyncio.sleep(jittered_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def fetch(self, url: str) -> str:
        """Fetch a URL as text. Rate-limited; retries on transient errors."""
        await self._rate_limit()
        return await self._fetch_with_retry(url)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=(
            retry_if_exception(
                lambda e: isinstance(e, httpx.HTTPStatusError)
                and e.response.status_code >= 500
            )
            | retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout))
        ),
        reraise=True,
    )
    async def _fetch_with_retry(self, url: str) -> str:
        """Tenacity handles 5xx/connection retries; 429 has its own loop below."""
        if self._client is None:
            raise RuntimeError("Client not initialized. Use 'async with GazetteClient()' context.")
        response = await self._client.get(url)
        # 429: honor Retry-After, fall back to the wait cycle
        cycle_index = 0
        while response.status_code == 429:
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
            response = await self._client.get(url)
        # raise on 5xx so tenacity does the exponential backoff
        if response.status_code >= 500:
            logger.warning("Server error %d for %s, will retry", response.status_code, url)
            response.raise_for_status()
        response.raise_for_status()
        return response.text
