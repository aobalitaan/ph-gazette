"""Masterlist scraper orchestration.

Phase A: paginate the results tables and collect metadata.
Phase B: fetch each content page (concurrent worker pool).
Phase C: download PDFs + extract text for pdf-only docs.
"""

import asyncio
import logging
import math
import signal
from datetime import UTC, datetime
from pathlib import Path

import httpx

from backend.pipeline.scraper.browser_client import BrowserFetchError, CurlCffiClient
from backend.pipeline.scraper.http_client import GazetteClient
from backend.pipeline.scraper.masterlist_parsers import (
    parse_masterlist_content_page,
    parse_masterlist_page,
    parse_total_records,
)
from backend.pipeline.scraper.masterlist_storage import MasterlistStorage
from backend.pipeline.scraper.models import (
    MASTERLIST_CATEGORY_MAP,
    MASTERLIST_PRESIDENT_SLUGS,
    MasterlistCorpusSummary,
    MasterlistDocument,
    MasterlistEntry,
    PdfStatus,
    ScrapeStatus,
)
from backend.pipeline.scraper.pdf_extractor import extract_pdf_text

logger = logging.getLogger(__name__)

MASTERLIST_BASE_URL = "https://www.officialgazette.gov.ph/masterlist-generator/"
DEFAULT_DATA_DIR = Path("data/documents-raw/masterlist")
PER_PAGE = 100

# SONAs come from the dedicated SONA scraper — filter them out of speeches here.
_SONA_KEYWORDS = ("state of the nation", "state-of-the-nation", "-sona-", "sona ")


def _build_page_url(category_slug: str, president_slug: str, page: int) -> str:
    if page == 1:
        return (
            f"{MASTERLIST_BASE_URL}"
            f"?category={category_slug}"
            f"&president={president_slug}"
            f"&per_page={PER_PAGE}"
            f"&on_order=ASC"
        )
    return (
        f"{MASTERLIST_BASE_URL}page/{page}/"
        f"?category={category_slug}"
        f"&president={president_slug}"
        f"&per_page={PER_PAGE}"
        f"&on_order=ASC"
    )


class MasterlistScraper:
    """Drives the masterlist scrape across all category × president combos."""

    def __init__(
        self,
        data_dir: Path = DEFAULT_DATA_DIR,
        delay: float = 5.0,
        force: bool = False,
        categories: list[str] | None = None,
        presidents: list[str] | None = None,
        concurrency: int = 1,
        proxies: list[str] | None = None,
    ) -> None:
        self.storage = MasterlistStorage(data_dir)
        self.delay = delay
        self.force = force
        self.categories = categories or list(MASTERLIST_CATEGORY_MAP.keys())
        self.presidents = presidents or list(MASTERLIST_PRESIDENT_SLUGS)
        self.concurrency = max(1, concurrency)
        self.proxies = proxies or []
        self._shutdown_requested = False
        self._documents: list[MasterlistDocument] = []

    @staticmethod
    def _is_sona(entry: MasterlistEntry) -> bool:
        """SONAs come from the dedicated scraper — skip them here."""
        title_lower = entry.title.lower()
        doc_id_lower = entry.doc_id.lower()
        return any(kw in title_lower or kw in doc_id_lower for kw in _SONA_KEYWORDS)

    async def run(self) -> MasterlistCorpusSummary:
        """Run phases A then B."""
        self.storage.ensure_dirs()
        self._setup_signal_handlers()

        async with GazetteClient(delay=self.delay) as client:
            await self._run_phase_a(client)

        if not self._shutdown_requested:
            await self._run_phase_b()

        self.storage.save_manifest(self._documents)
        summary = self._build_summary()
        logger.info(
            "Done. %d success, %d failed, %d pending, %d pdf_only, %d html_with_text",
            summary.success,
            summary.failed,
            summary.pending,
            summary.pdf_only,
            summary.html_with_text,
        )
        return summary

    async def run_phase_a_only(self) -> int:
        """Phase A only — returns total entry count."""
        self.storage.ensure_dirs()
        self._setup_signal_handlers()
        total = 0
        async with GazetteClient(delay=self.delay) as client:
            total = await self._run_phase_a(client)
        return total

    async def run_phase_b_only(self) -> MasterlistCorpusSummary:
        """Phase B only — content fetching from existing indexes."""
        self.storage.ensure_dirs()
        self._setup_signal_handlers()

        await self._run_phase_b()

        self.storage.save_manifest(self._documents)
        return self._build_summary()

    async def run_phase_c_only(self) -> MasterlistCorpusSummary:
        """Phase C only — PDF download + text extraction from existing manifest."""
        self.storage.ensure_dirs()
        self._setup_signal_handlers()

        self._documents = self.storage.load_manifest()
        if not self._documents:
            logger.warning("No manifest found. Run Phase A + B first.")
            return self._build_summary()

        await self._run_phase_c()

        self.storage.save_manifest(self._documents)
        return self._build_summary()

    async def _run_phase_a(self, client: GazetteClient) -> int:
        """Walk every category × president, collecting masterlist rows."""
        combinations = [
            (cat, pres) for cat in self.categories for pres in self.presidents
        ]
        total_entries = 0

        for i, (cat, pres) in enumerate(combinations):
            if self._shutdown_requested:
                logger.info("Shutdown requested, stopping Phase A...")
                break

            if not self.force:
                cached = self.storage.load_index(cat, pres)
                if cached is not None:
                    count = len(cached)
                    total_entries += count
                    logger.debug(
                        "[%d/%d] %s × %s: %d records (cached)",
                        i + 1, len(combinations), cat, pres, count,
                    )
                    continue

            url = _build_page_url(cat, pres, 1)
            try:
                html = await client.fetch(url)
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "[%d/%d] %s × %s: HTTP %d, skipping",
                    i + 1, len(combinations), cat, pres, e.response.status_code,
                )
                self.storage.save_index(cat, pres, [])
                continue

            total_records = parse_total_records(html)
            if total_records == 0:
                logger.debug(
                    "[%d/%d] %s × %s: 0 records",
                    i + 1, len(combinations), cat, pres,
                )
                self.storage.save_index(cat, pres, [])
                continue

            entries = parse_masterlist_page(html, cat)
            total_pages = math.ceil(total_records / PER_PAGE)

            for page_num in range(2, total_pages + 1):
                if self._shutdown_requested:
                    break
                page_url = _build_page_url(cat, pres, page_num)
                try:
                    page_html = await client.fetch(page_url)
                    entries.extend(parse_masterlist_page(page_html, cat))
                except Exception as e:
                    logger.warning(
                        "  Page %d/%d failed for %s × %s: %s",
                        page_num, total_pages, cat, pres, e,
                    )

            before = len(entries)
            entries = [e for e in entries if not self._is_sona(e)]
            sona_count = before - len(entries)

            self.storage.save_index(cat, pres, entries)
            total_entries += len(entries)
            sona_msg = f", {sona_count} SONAs filtered" if sona_count else ""
            logger.info(
                "[%d/%d] %s × %s: %d records (%d pages%s)",
                i + 1, len(combinations), cat, pres, len(entries), total_pages,
                sona_msg,
            )

        logger.info("Phase A complete: %d total entries indexed", total_entries)
        return total_entries

    async def _run_phase_b(self) -> None:
        """Fetch content pages using a concurrent curl_cffi worker pool."""
        # dedupe by doc_id across the loaded indexes
        all_entries = self.storage.load_all_index_entries()
        seen: dict[str, MasterlistEntry] = {}
        sona_skipped = 0
        for entry in all_entries:
            if entry.category_slug not in self.categories:
                continue
            if entry.president_slug not in self.presidents:
                continue
            if self._is_sona(entry):
                sona_skipped += 1
                continue
            if entry.doc_id not in seen:
                seen[entry.doc_id] = entry
        unique_entries = list(seen.values())

        logger.info(
            "Phase B: %d unique entries to process (%d SONA duplicates skipped, %d total)",
            len(unique_entries), sona_skipped, len(all_entries),
        )

        self._documents = self._build_document_list(unique_entries)
        pending = [d for d in self._documents if d.scrape_status != ScrapeStatus.SUCCESS]
        logger.info(
            "%d total documents, %d already scraped, %d to scrape (%d workers)",
            len(self._documents),
            len(self._documents) - len(pending),
            len(pending),
            self.concurrency,
        )

        if not pending:
            return

        queue: asyncio.Queue[MasterlistDocument] = asyncio.Queue()
        for doc in pending:
            queue.put_nowait(doc)

        self._progress = 0
        self._completed_since_save = 0
        total = len(pending)

        async def worker(worker_id: int) -> None:
            proxy = (
                self.proxies[worker_id]
                if worker_id < len(self.proxies)
                else None
            )
            async with CurlCffiClient(
                delay=self.delay, proxy=proxy,
            ) as client:
                while not self._shutdown_requested:
                    try:
                        doc = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    self._progress += 1
                    n = self._progress
                    logger.info(
                        "[%d/%d] W%d: %s (%s/%s)",
                        n, total, worker_id,
                        doc.doc_id, doc.category_slug, doc.president_slug,
                    )
                    await self._scrape_one(client, doc)

                    # checkpoint every 500 docs
                    self._completed_since_save += 1
                    if self._completed_since_save >= 500:
                        self._completed_since_save = 0
                        self.storage.save_manifest(self._documents)
                        logger.info("Manifest checkpoint saved (%d/%d)", n, total)

        workers = [
            asyncio.create_task(worker(i))
            for i in range(self.concurrency)
        ]
        await asyncio.gather(*workers)

    def _build_document_list(
        self, entries: list[MasterlistEntry]
    ) -> list[MasterlistDocument]:
        """Merge new entries with the existing manifest so --categories doesn't
        wipe out docs from other categories."""
        existing: dict[str, MasterlistDocument] = {}
        if not self.force:
            for doc in self.storage.load_manifest():
                existing[doc.doc_id] = doc

        entry_doc_ids: set[str] = set()
        documents: list[MasterlistDocument] = []
        for entry in entries:
            entry_doc_ids.add(entry.doc_id)
            if (
                entry.doc_id in existing
                and existing[entry.doc_id].scrape_status == ScrapeStatus.SUCCESS
            ):
                documents.append(existing[entry.doc_id])
            else:
                documents.append(MasterlistDocument.from_entry(entry))

        # keep manifest docs outside the current --categories filter
        for doc_id, doc in existing.items():
            if doc_id not in entry_doc_ids:
                documents.append(doc)

        return documents

    async def _scrape_one(
        self, client: GazetteClient | CurlCffiClient, doc: MasterlistDocument,
    ) -> None:
        """Scrape one content page. Errors are non-fatal."""
        try:
            html = await client.fetch(doc.content_url)
            parsed = parse_masterlist_content_page(html)

            doc.text = parsed["text"]
            doc.word_count = parsed["word_count"]
            doc.has_html_content = parsed["has_html_content"]
            doc.is_pdf_only = parsed["is_pdf_only"]
            # content-page PDF wins over the masterlist-table one
            if parsed["pdf_url"]:
                doc.pdf_url = parsed["pdf_url"]
            doc.scrape_status = ScrapeStatus.SUCCESS
            doc.scraped_at = datetime.now(UTC)

            self.storage.save_document(doc, html)
            if doc.has_html_content:
                logger.info("  OK: %d words (HTML)", doc.word_count or 0)
            else:
                logger.info("  OK: PDF-only stub")

        except BrowserFetchError as e:
            doc.scrape_status = ScrapeStatus.FAILED
            doc.scrape_error = f"HTTP {e.status}"
            doc.scraped_at = datetime.now(UTC)
            self.storage.save_metadata(doc)
            logger.error("  FAILED: %s — HTTP %d", doc.doc_id, e.status)

        except httpx.HTTPStatusError as e:
            doc.scrape_status = ScrapeStatus.FAILED
            doc.scrape_error = f"HTTP {e.response.status_code}"
            doc.scraped_at = datetime.now(UTC)
            self.storage.save_metadata(doc)
            logger.error("  FAILED: %s — HTTP %d", doc.doc_id, e.response.status_code)

        except Exception as e:
            doc.scrape_status = ScrapeStatus.FAILED
            doc.scrape_error = str(e)
            doc.scraped_at = datetime.now(UTC)
            self.storage.save_metadata(doc)
            logger.error("  FAILED: %s — %s", doc.doc_id, e)

    async def _run_phase_c(self) -> None:
        """Download PDFs for pdf-only docs and extract text."""
        pending: list[MasterlistDocument] = []
        for doc in self._documents:
            if not doc.is_pdf_only:
                continue
            if doc.category_slug not in self.categories:
                continue
            if doc.president_slug not in self.presidents:
                continue
            if not self.force and doc.pdf_status in (
                PdfStatus.TEXT_EXTRACTED, PdfStatus.OCR_EXTRACTED,
            ):
                continue
            if not doc.pdf_url:
                doc.pdf_status = PdfStatus.SKIPPED
                doc.pdf_error = "no pdf_url"
                doc.pdf_processed_at = datetime.now(UTC)
                continue
            pending.append(doc)

        skipped = sum(1 for d in self._documents if d.pdf_status == PdfStatus.SKIPPED)
        already = sum(
            1 for d in self._documents
            if d.pdf_status in (PdfStatus.TEXT_EXTRACTED, PdfStatus.OCR_EXTRACTED)
        )
        logger.info(
            "Phase C: %d PDFs to process (%d already done, %d skipped, %d workers)",
            len(pending), already, skipped, self.concurrency,
        )

        if not pending:
            return

        queue: asyncio.Queue[MasterlistDocument] = asyncio.Queue()
        for doc in pending:
            queue.put_nowait(doc)

        self._progress = 0
        self._completed_since_save = 0
        total = len(pending)

        async def worker(worker_id: int) -> None:
            proxy = (
                self.proxies[worker_id]
                if worker_id < len(self.proxies)
                else None
            )
            async with CurlCffiClient(
                delay=self.delay, proxy=proxy,
            ) as client:
                while not self._shutdown_requested:
                    try:
                        doc = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    self._progress += 1
                    n = self._progress
                    logger.info(
                        "[%d/%d] W%d: %s (%s/%s)",
                        n, total, worker_id,
                        doc.doc_id, doc.category_slug, doc.president_slug,
                    )
                    await self._process_pdf(client, doc)

                    self._completed_since_save += 1
                    if self._completed_since_save >= 200:
                        self._completed_since_save = 0
                        self.storage.save_manifest(self._documents)
                        logger.info("Manifest checkpoint saved (%d/%d)", n, total)

        workers = [
            asyncio.create_task(worker(i))
            for i in range(self.concurrency)
        ]
        await asyncio.gather(*workers)

    async def _process_pdf(
        self, client: CurlCffiClient, doc: MasterlistDocument,
    ) -> None:
        """Download (or load cached) PDF, extract text, update the document."""
        try:
            pdf_bytes = self.storage.load_pdf(doc)
            if pdf_bytes is None:
                assert doc.pdf_url is not None
                pdf_bytes = await client.fetch_bytes(doc.pdf_url)
                self.storage.save_pdf(doc, pdf_bytes)
                logger.debug("  Downloaded PDF (%d bytes)", len(pdf_bytes))
            else:
                logger.debug("  PDF loaded from disk (%d bytes)", len(pdf_bytes))

            # CPU-bound, off the event loop
            result = await asyncio.to_thread(extract_pdf_text, pdf_bytes)

            doc.pdf_processed_at = datetime.now(UTC)

            if result.text:
                doc.text = result.text
                doc.word_count = result.word_count
                doc.pdf_status = PdfStatus(result.method)
                doc.pdf_error = None
                self.storage.save_text(doc, result.text)
                self.storage.save_metadata(doc)
                logger.info("  OK: %d words (%s)", result.word_count, result.method)
            else:
                doc.pdf_status = PdfStatus.FAILED
                doc.pdf_error = result.error
                self.storage.save_metadata(doc)
                logger.warning("  FAILED: %s", result.error)

        except BrowserFetchError as e:
            doc.pdf_status = PdfStatus.FAILED
            doc.pdf_error = f"HTTP {e.status}"
            doc.pdf_processed_at = datetime.now(UTC)
            self.storage.save_metadata(doc)
            logger.error("  PDF FAILED: %s — HTTP %d", doc.doc_id, e.status)

        except Exception as e:
            doc.pdf_status = PdfStatus.FAILED
            doc.pdf_error = str(e)
            doc.pdf_processed_at = datetime.now(UTC)
            self.storage.save_metadata(doc)
            logger.error("  PDF FAILED: %s — %s", doc.doc_id, e)

    def _build_summary(self) -> MasterlistCorpusSummary:
        by_category: dict[str, int] = {}
        by_president: dict[str, int] = {}
        for d in self._documents:
            by_category[d.category_slug] = by_category.get(d.category_slug, 0) + 1
            by_president[d.president_slug] = by_president.get(d.president_slug, 0) + 1

        return MasterlistCorpusSummary(
            total=len(self._documents),
            success=sum(
                1 for d in self._documents if d.scrape_status == ScrapeStatus.SUCCESS
            ),
            failed=sum(
                1 for d in self._documents if d.scrape_status == ScrapeStatus.FAILED
            ),
            pending=sum(
                1 for d in self._documents if d.scrape_status == ScrapeStatus.PENDING
            ),
            skipped=sum(
                1 for d in self._documents if d.scrape_status == ScrapeStatus.SKIPPED
            ),
            pdf_only=sum(1 for d in self._documents if d.is_pdf_only),
            html_with_text=sum(1 for d in self._documents if d.has_html_content),
            by_category=by_category,
            by_president=by_president,
            total_words=sum(d.word_count or 0 for d in self._documents),
            pdf_text_extracted=sum(
                1 for d in self._documents if d.pdf_status == PdfStatus.TEXT_EXTRACTED
            ),
            pdf_ocr_extracted=sum(
                1 for d in self._documents if d.pdf_status == PdfStatus.OCR_EXTRACTED
            ),
            pdf_failed=sum(
                1 for d in self._documents if d.pdf_status == PdfStatus.FAILED
            ),
            pdf_skipped=sum(
                1 for d in self._documents if d.pdf_status == PdfStatus.SKIPPED
            ),
        )

    def _setup_signal_handlers(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_shutdown)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

    def _handle_shutdown(self) -> None:
        """First Ctrl+C flags shutdown so we can save state; second forces exit."""
        if self._shutdown_requested:
            logger.warning("Force shutdown requested, exiting immediately")
            raise SystemExit(1)
        logger.info("Shutdown requested, finishing current document...")
        self._shutdown_requested = True
