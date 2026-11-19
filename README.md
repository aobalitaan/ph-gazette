# Philippine Official Gazette Scraper

Scrapes presidential documents from the [Official Gazette of the Philippines](https://www.officialgazette.gov.ph/) for research.

There are two scrapers:

- **SONA** — all 87 State of the Nation Addresses from 1935 to 2025.
- **Masterlist** — executive orders, proclamations, speeches, and other issuances from 15 presidents.

The scraped text is included here, so you can use the data without running the scraper.

## Setup

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required. For OCR on scanned PDFs, also install [Tesseract](https://github.com/tesseract-ocr/tesseract).

```bash
git clone https://github.com/aobalitaan/ph-gazette.git
cd ph-gazette
uv sync
```

## Scraping

```bash
# all SONAs
uv run talasuri-scrape-sona

# the whole masterlist (takes a long time)
uv run talasuri-scrape-masterlist
```

Options you will probably want:

```bash
# collect only the masterlist index, no document pages
uv run talasuri-scrape-masterlist --index-only

# fetch page text using an index collected earlier
uv run talasuri-scrape-masterlist --content-only

# extract text from documents that only have a PDF
uv run talasuri-scrape-masterlist --pdf-only

# limit by category or president
uv run talasuri-scrape-masterlist --categories executive-orders proclamations
uv run talasuri-scrape-masterlist --presidents rodrigo-roa-duterte ferdinand-r-marcos

# 3 workers, verbose output, 5 seconds between requests
uv run talasuri-scrape-masterlist -c 3 -v --delay 5
```

Both scrapers skip documents already on disk. Use `--force` to start over. Ctrl+C stops a run cleanly and the next run picks up where it left off.

## How the scraper works

**SONA** reads the past SONA speeches page, takes the links from the table, then opens each speech and saves its text.

The masterlist has three phases:

1. **Index** — pages through the Gazette's masterlist generator and saves each result's metadata (title, date, president, page URL, PDF URL) as JSON. This phase uses plain `httpx`; these pages are not blocked.
2. **Content** — opens each document page and extracts the text. This uses `curl_cffi`, which copies a real browser's TLS fingerprint so Cloudflare does not block the requests.
3. **PDF** — downloads the PDF for documents that have no text on the page. PyMuPDF pulls the text layer; if it is missing or poor, the pages are rendered and run through Tesseract OCR. A check on letter ratio, average word length, and minimum word count discards bad OCR output.

## Request delay

The default delay is **5 seconds** between requests, with ±50% jitter (about 2.5–7.5 seconds in practice). The Gazette blocks fast scraping, so leave it at 5 seconds unless you have a reason not to. Below 2 seconds you will hit HTTP 429.

VPN and proxy IPs often get a Cloudflare challenge. If every request returns 403, try a normal connection first.

To spread requests over several IPs, pass a proxy file with one `host:port:user:pass` per line. The scraper uses one worker per proxy.

```bash
uv run talasuri-scrape-masterlist --proxy-file proxies.txt
```

## Output

```
data/documents-raw/
  sona/
    raw_html/{president}/{doc_id}.html
    text/{president}/{doc_id}.txt
    metadata/{president}/{doc_id}.json
    manifest.json
  masterlist/
    index/{category}/{president}.json
    raw_html/{category}/{president}/{doc_id}.html
    text/{category}/{president}/{doc_id}.txt
    metadata/{category}/{president}/{doc_id}.json
    pdf/{category}/{president}/{doc_id}.pdf
    manifest.json
```

**Index files** are the phase 1 output. They are a cached table of contents for each category and president, so you do not have to page through the search form again. They contain metadata only, not document text.

**Manifest** records the status of every document (success, failed, pending) and when it was last scraped. That is what makes resuming possible. Manifests are not committed because they are too large for GitHub; the scraper rebuilds them from the metadata files on the first run.

A metadata file looks like this:

```json
{
  "doc_id": "executive-order-no-01-s-2016",
  "category": "executive_order",
  "category_slug": "executive-orders",
  "president_slug": "rodrigo-roa-duterte",
  "date": "2016-07-26",
  "title": "Executive Order No. 01, s. 2016",
  "content_url": "https://www.officialgazette.gov.ph/2016/07/26/executive-order-no-01-s-2016/",
  "pdf_url": "https://www.officialgazette.gov.ph/.../20160726-EO-1-RRD.pdf",
  "word_count": 542,
  "has_html_content": true,
  "is_pdf_only": false,
  "scrape_status": "success",
  "scraped_at": "2026-02-23T08:15:00Z",
  "pdf_status": "not_applicable",
  "pdf_error": null,
  "pdf_processed_at": null
}
```

For PDF-only documents, `pdf_status` is `text_extracted`, `ocr_extracted`, `failed`, `skipped`, or `pending`.

## Included data

| Collection | Documents |
| --- | --- |
| SONAs, 1935–2025 | 87 |
| Masterlist | 34,015 |
| Translated text | 38,175 |

Of the 34,015 masterlist documents, 138 are PDF-only.

The translated set contains every document after translation. Most were already in English; 2,108 Filipino or Taglish documents were translated through OpenRouter (`google/gemma-3-27b-it`). Bad translations were reviewed and corrected.

`data/documents-translated/` follows the masterlist layout: `{category}/{president}/{doc_id}.txt`.

## Categories

| Category | Slug |
| --- | --- |
| Executive Orders | `executive-orders` |
| Administrative Orders | `administrative-orders` |
| Proclamations | `proclamations` |
| Memorandum Orders | `memorandum-orders` |
| Memorandum Circulars | `memorandum-circulars` |
| Presidential Decrees | `presidential-decrees-executive-issuances` |
| Speeches | `speeches` |
| Republic Acts | `republic-acts` |
| General Orders | `general-orders` |
| Letters of Instruction | `letters-of-instruction` |
| Letters of Implementation | `letters-of-implementation` |
| Other Issuances | `other-issuances` |
| Special Orders | `special-orders` |
| IRR (Executive Orders) | `implementing-rules-and-regulations-executive-orders` |
| IRR (Republic Acts) | `implementing-rules-and-regulations` |

## Tests

```bash
uv run pytest
```

## Layout

```
backend/pipeline/scraper/
  sona_scraper.py, masterlist_scraper.py   # scrape logic
  parsers.py, masterlist_parsers.py        # HTML parsing
  storage.py, masterlist_storage.py        # file output
  browser_client.py, http_client.py        # HTTP clients
  pdf_extractor.py                         # PDF text + OCR
  models.py, cli.py, masterlist_cli.py     # models and command line
tests/pipeline/scraper/                    # unit tests
tests/fixtures/                            # sample Gazette HTML
```

## Source

Text comes from the [Official Gazette of the Republic of the Philippines](https://www.officialgazette.gov.ph/). This project is for academic research.

## License

MIT
