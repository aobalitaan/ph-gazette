"""File I/O for masterlist scraper output (raw HTML, text, metadata,
per-combo index caches, and the combined manifest)."""

import json
from pathlib import Path

from backend.pipeline.scraper.models import MasterlistDocument, MasterlistEntry


class MasterlistStorage:
    """File layout::

        base_dir/
            raw_html/{category_slug}/{president_slug}/{doc_id}.html
            text/{category_slug}/{president_slug}/{doc_id}.txt
            metadata/{category_slug}/{president_slug}/{doc_id}.json
            pdf/{category_slug}/{president_slug}/{doc_id}.pdf
            index/{category_slug}/{president_slug}.json
            manifest.json
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_html_dir = base_dir / "raw_html"
        self.text_dir = base_dir / "text"
        self.metadata_dir = base_dir / "metadata"
        self.pdf_dir = base_dir / "pdf"
        self.index_dir = base_dir / "index"
        self.manifest_path = base_dir / "manifest.json"

    def ensure_dirs(self) -> None:
        for d in (
            self.raw_html_dir, self.text_dir, self.metadata_dir,
            self.pdf_dir, self.index_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def save_raw_html(self, doc: MasterlistDocument, html: str) -> Path:
        path = self._doc_path(self.raw_html_dir, doc, ".html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return path

    def save_text(self, doc: MasterlistDocument, text: str) -> Path:
        path = self._doc_path(self.text_dir, doc, ".txt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def save_metadata(self, doc: MasterlistDocument) -> Path:
        path = self._doc_path(self.metadata_dir, doc, ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
        return path

    def save_document(self, doc: MasterlistDocument, html: str) -> None:
        """Save all artifacts for one document."""
        self.save_raw_html(doc, html)
        if doc.text:
            self.save_text(doc, doc.text)
        self.save_metadata(doc)

    def save_pdf(self, doc: MasterlistDocument, pdf_bytes: bytes) -> Path:
        path = self._doc_path(self.pdf_dir, doc, ".pdf")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf_bytes)
        return path

    def load_pdf(self, doc: MasterlistDocument) -> bytes | None:
        """Cached PDF bytes, or None if not on disk."""
        path = self._doc_path(self.pdf_dir, doc, ".pdf")
        if not path.exists():
            return None
        return path.read_bytes()

    def has_pdf(self, doc: MasterlistDocument) -> bool:
        return self._doc_path(self.pdf_dir, doc, ".pdf").exists()

    def save_index(
        self, category_slug: str, president_slug: str, entries: list[MasterlistEntry]
    ) -> Path:
        """Cache Phase A entries for a category × president combo."""
        path = self.index_dir / category_slug / f"{president_slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [json.loads(e.model_dump_json()) for e in entries]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load_index(
        self, category_slug: str, president_slug: str
    ) -> list[MasterlistEntry] | None:
        path = self.index_dir / category_slug / f"{president_slug}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return [MasterlistEntry(**entry) for entry in data]

    def load_all_index_entries(self) -> list[MasterlistEntry]:
        """Flatten every saved index file into one list."""
        entries: list[MasterlistEntry] = []
        if not self.index_dir.exists():
            return entries
        for json_file in sorted(self.index_dir.rglob("*.json")):
            data = json.loads(json_file.read_text(encoding="utf-8"))
            entries.extend(MasterlistEntry(**entry) for entry in data)
        return entries

    def load_manifest(self) -> list[MasterlistDocument]:
        if not self.manifest_path.exists():
            return []
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return [MasterlistDocument(**entry) for entry in data]

    def save_manifest(self, documents: list[MasterlistDocument]) -> Path:
        data = [json.loads(doc.model_dump_json()) for doc in documents]
        self.manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return self.manifest_path

    def get_scraped_doc_ids(self) -> set[str]:
        """Set of doc_ids already marked success, for O(1) lookups."""
        return {
            doc.doc_id
            for doc in self.load_manifest()
            if doc.scrape_status == "success"
        }

    def _doc_path(self, base: Path, doc: MasterlistDocument, ext: str) -> Path:
        return base / doc.category_slug / doc.president_slug / f"{doc.doc_id}{ext}"
