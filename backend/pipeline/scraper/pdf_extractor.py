"""PDF text extraction with quality gate and OCR fallback.

Sync module — call via asyncio.to_thread() since OCR is CPU-bound.
Tries pymupdf text-layer first; falls back to Tesseract OCR if quality fails.
"""

import logging
import re
from dataclasses import dataclass

import fitz  # pymupdf
import pytesseract
from PIL import Image

from backend.pipeline.preprocessing.boilerplate import strip_garbage_lines

logger = logging.getLogger(__name__)

MIN_ALPHA_RATIO = 0.70
MIN_AVG_WORD_LEN = 2.0
MAX_AVG_WORD_LEN = 15.0
MIN_WORD_COUNT = 50

# 200 DPI is the sweet spot for Tesseract on these documents
OCR_DPI = 200


@dataclass(frozen=True)
class QualityResult:

    passed: bool
    word_count: int
    alpha_ratio: float
    avg_word_len: float
    reason: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    text: str | None
    word_count: int
    method: str  # "text_extracted", "ocr_extracted", or "failed"
    error: str | None = None


def check_quality(text: str) -> QualityResult:
    """Language-agnostic gate: alpha-ratio >= 0.70, avg word len 2-15, >= 50 words."""
    tokens = text.split()
    word_count = len(tokens)

    if word_count < MIN_WORD_COUNT:
        return QualityResult(
            passed=False,
            word_count=word_count,
            alpha_ratio=0.0,
            avg_word_len=0.0,
            reason=f"too few words ({word_count} < {MIN_WORD_COUNT})",
        )

    alpha_tokens = sum(1 for t in tokens if re.search(r"[a-zA-Z]", t))
    alpha_ratio = alpha_tokens / word_count

    avg_word_len = sum(len(t) for t in tokens) / word_count

    if alpha_ratio < MIN_ALPHA_RATIO:
        return QualityResult(
            passed=False,
            word_count=word_count,
            alpha_ratio=alpha_ratio,
            avg_word_len=avg_word_len,
            reason=f"low alphabetic ratio ({alpha_ratio:.2f} < {MIN_ALPHA_RATIO})",
        )

    if avg_word_len < MIN_AVG_WORD_LEN or avg_word_len > MAX_AVG_WORD_LEN:
        return QualityResult(
            passed=False,
            word_count=word_count,
            alpha_ratio=alpha_ratio,
            avg_word_len=avg_word_len,
            reason=(
                f"avg word length {avg_word_len:.1f} outside "
                f"[{MIN_AVG_WORD_LEN}, {MAX_AVG_WORD_LEN}]"
            ),
        )

    return QualityResult(
        passed=True,
        word_count=word_count,
        alpha_ratio=alpha_ratio,
        avg_word_len=avg_word_len,
    )


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """pymupdf text-layer extraction, pages joined by newlines."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = []
        for page in doc:
            text = page.get_text()
            if text.strip():
                pages.append(text)
        return "\n".join(pages)
    finally:
        doc.close()


# Below this average Tesseract confidence we try a 180° rotation.
# Correctly-oriented text scores >90; upside-down text scores ~40-60.
_MIN_OCR_CONFIDENCE = 70


def _avg_confidence(img: Image.Image) -> float:
    """Tesseract's mean per-word confidence."""
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    confs = [int(c) for c in data["conf"] if int(c) > 0]
    return sum(confs) / len(confs) if confs else 0.0


def _ocr_image(img: Image.Image) -> str:
    """OCR an image; try 180° rotation if confidence is low.

    Some scanned pages are upside-down with no orientation metadata. The
    confidence gap (~49% vs ~95%) is what tells us to rotate.
    """
    text = pytesseract.image_to_string(img)
    if not text.strip():
        return text

    conf = _avg_confidence(img)
    if conf >= _MIN_OCR_CONFIDENCE:
        return text

    rotated = img.rotate(180, expand=True)
    rotated_text = pytesseract.image_to_string(rotated)
    rotated_conf = _avg_confidence(rotated)

    if rotated_conf > conf:
        logger.info(
            "Page OCR improved with 180° rotation (%.0f%% → %.0f%%)",
            conf, rotated_conf,
        )
        return rotated_text

    return text


def ocr_pdf(pdf_bytes: bytes) -> str:
    """Render pages at OCR_DPI and run Tesseract; auto-corrects 180° rotation."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pages = []
        mat = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = _ocr_image(img)
            if text.strip():
                pages.append(text)
        return "\n".join(pages)
    finally:
        doc.close()


def extract_pdf_text(pdf_bytes: bytes) -> ExtractionResult:
    """Text-layer first, OCR fallback. Each path goes through the quality gate."""
    try:
        text = extract_text_from_pdf(pdf_bytes)
    except Exception as e:
        logger.warning("pymupdf text extraction failed: %s", e)
        text = ""

    if text.strip():
        text = strip_garbage_lines(text)

    if text.strip():
        qr = check_quality(text)
        if qr.passed:
            return ExtractionResult(
                text=text.strip(),
                word_count=qr.word_count,
                method="text_extracted",
            )
        logger.debug("Text layer failed quality gate: %s", qr.reason)

    try:
        ocr_text = ocr_pdf(pdf_bytes)
    except Exception as e:
        logger.warning("OCR failed: %s", e)
        # report the text-layer reason if we had something there
        if text.strip():
            qr = check_quality(text)
            return ExtractionResult(
                text=None,
                word_count=qr.word_count,
                method="failed",
                error=f"text quality gate failed ({qr.reason}), OCR also failed ({e})",
            )
        return ExtractionResult(
            text=None,
            word_count=0,
            method="failed",
            error=f"no text layer, OCR failed ({e})",
        )

    if ocr_text.strip():
        ocr_text = strip_garbage_lines(ocr_text)

    if ocr_text.strip():
        qr = check_quality(ocr_text)
        if qr.passed:
            return ExtractionResult(
                text=ocr_text.strip(),
                word_count=qr.word_count,
                method="ocr_extracted",
            )
        return ExtractionResult(
            text=None,
            word_count=qr.word_count,
            method="failed",
            error=f"OCR quality gate failed ({qr.reason})",
        )

    return ExtractionResult(
        text=None,
        word_count=0,
        method="failed",
        error="no text from text layer or OCR",
    )
