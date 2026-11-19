"""HTML parsers for Official Gazette masterlist pages. No I/O."""

import html as html_mod
import re

from bs4 import BeautifulSoup, Tag

from backend.pipeline.preprocessing.boilerplate import _classify_garbage
from backend.pipeline.scraper.models import MasterlistEntry
from backend.pipeline.scraper.parsers import parse_gazette_date


def parse_masterlist_page(html: str, category_slug: str) -> list[MasterlistEntry]:
    """Parse the results table. Columns: Title | Content URL | President | Date | PDF (optional)."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    rows = table.find_all("tr")
    entries: list[MasterlistEntry] = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        title = cells[0].get_text(strip=True)
        if not title:
            continue

        content_link = cells[1].find("a", href=True)
        if not content_link:
            continue
        content_url = content_link["href"]

        president_slug = cells[2].get_text(strip=True)
        date_text = cells[3].get_text(strip=True)
        parsed_date = parse_gazette_date(date_text)
        if parsed_date is None:
            continue

        # 5th column (PDF) may be missing or empty
        pdf_url = None
        if len(cells) >= 5:
            pdf_link = cells[4].find("a", href=True)
            if pdf_link and pdf_link["href"].endswith(".pdf"):
                pdf_url = pdf_link["href"]

        entries.append(
            MasterlistEntry(
                title=title,
                content_url=content_url,
                president_slug=president_slug,
                date=parsed_date,
                pdf_url=pdf_url,
                category_slug=category_slug,
            )
        )

    return entries


def parse_total_records(html: str) -> int:
    """Pull the count out of 'There are X total number of records found.'"""
    match = re.search(r"There are (\d+) total number of records found", html)
    if match:
        return int(match.group(1))
    return 0


def parse_masterlist_content_page(html: str) -> dict:
    """Parse a content page; returns text, word_count, has_html_content, is_pdf_only, pdf_url."""
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article")
    if not article:
        raise ValueError("No <article> element found in content page HTML")

    # grab PDF before stripping the Resources block
    pdf_url = _extract_pdf_url(article)

    content = article.find(class_="entry-content")
    if content is None:
        content = article

    _remove_resources_section(content)

    paragraphs = _extract_paragraphs(content)
    text = "\n\n".join(paragraphs)
    word_count = len(text.split()) if text else 0

    # Many gazette pages are just title+document-number stubs with the real
    # content in the PDF. 100 words filters those out.
    has_html_content = word_count >= 100
    is_pdf_only = not has_html_content

    return {
        "text": text if has_html_content else None,
        "word_count": word_count if has_html_content else None,
        "has_html_content": has_html_content,
        "is_pdf_only": is_pdf_only,
        "pdf_url": pdf_url,
    }


# Header lines that show up at the top of most gazette documents.
_BOILERPLATE_PATTERNS = frozenset({
    "malacañan palace",
    "malacañang palace",
    "malacanan palace",
    "manila",
    "by the president of the philippines",
})


def _extract_paragraphs(content: Tag) -> list[str]:
    """Pull paragraphs, dropping boilerplate header lines and garbage."""
    paragraphs = []
    for p in content.find_all("p", recursive=True):
        text = p.get_text(separator=" ", strip=True)
        if not text or text == "\xa0":
            continue
        if text.lower() in _BOILERPLATE_PATTERNS:
            continue
        if _classify_garbage(text):
            continue
        paragraphs.append(html_mod.unescape(text))
    return paragraphs


def _extract_pdf_url(article: Tag) -> str | None:
    """First link ending in .pdf, if any."""
    for link in article.find_all("a", href=True):
        href = link["href"]
        if href.endswith(".pdf"):
            return href
    return None


def _remove_resources_section(content: Tag) -> None:
    """Drop the Resources block so its links don't end up in the text."""
    for heading in content.find_all("h5"):
        if heading.get_text(strip=True) == "Resources":
            parent = heading.find_parent("section") or heading.find_parent(
                "div", class_="row"
            )
            if parent:
                parent.decompose()
            else:
                heading.decompose()
