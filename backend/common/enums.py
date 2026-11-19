"""Shared enums — single source of truth for scraper, app, and pipeline."""

from enum import StrEnum


class DocumentCategory(StrEnum):
    """Document types from the Official Gazette."""

    SONA = "sona"
    EXECUTIVE_ORDER = "executive_order"
    ADMINISTRATIVE_ORDER = "administrative_order"
    PROCLAMATION = "proclamation"
    MEMORANDUM_ORDER = "memorandum_order"
    MEMORANDUM_CIRCULAR = "memorandum_circular"
    PRESIDENTIAL_DECREE = "presidential_decree"
    SPEECH = "speech"
    REPUBLIC_ACT = "republic_act"
    GENERAL_ORDER = "general_order"
    LETTER_OF_INSTRUCTION = "letter_of_instruction"
    LETTER_OF_IMPLEMENTATION = "letter_of_implementation"
    OTHER_ISSUANCE = "other_issuance"
    SPECIAL_ORDER = "special_order"
    IRR_EXECUTIVE_ORDER = "irr_executive_order"
    IRR_REPUBLIC_ACT = "irr_republic_act"


class ScrapeStatus(StrEnum):

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PdfStatus(StrEnum):

    PENDING = "pending"
    TEXT_EXTRACTED = "text_extracted"
    OCR_EXTRACTED = "ocr_extracted"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"
    # set by scripts/scrape_alt_sources.py
    ALT_SOURCE_LAWPHIL = "alt_source_lawphil"
    ALT_SOURCE_CHANROBLES = "alt_source_chanrobles"
    ALT_SOURCE_WAYBACK = "alt_source_wayback"
    ALT_SOURCE_WAYBACK_HTML = "alt_source_wayback_html"
