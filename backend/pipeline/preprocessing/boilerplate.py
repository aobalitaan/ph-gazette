"""Boilerplate stripping for presidential documents.

Removes legal scaffolding, headers, stage directions, and metadata so topic
modeling receives clean policy content. Category-dispatched: SONAs, speeches,
issuances each have tailored pattern sets.
"""

import asyncio
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PatternSet:

    header_patterns: list[tuple[re.Pattern, str]]
    header_limit: int
    line_patterns: list[tuple[re.Pattern, str]]
    inline_patterns: list[tuple[re.Pattern, str]]
    tail_patterns: list[tuple[re.Pattern, str]]
    tail_limit: int


@dataclass(frozen=True)
class BoilerplateResult:
    cleaned_text: str
    patterns_removed: list[str]
    chars_removed: int


# SONA patterns (header_limit=15, tail_limit=0)

_SONA_HEADER = [
    (re.compile(
        r"(?i)^STATE\s+OF\s+THE\s+NATION\s+ADDRESS"
        r"(?:\s+OF\s+.*PRESIDENT.*)?$"
    ), "sona_title"),
    (re.compile(
        r"(?i)^MESSAGE\s+OF\s+(?:HIS|HER)\s+EXCELLENCY\b.*$"
    ), "sona_excellency_header"),
    (re.compile(
        r"(?i)^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+"
        r"STATE\s+OF\s+THE\s+NATION\s+ADDRESS\b.*$"
    ), "sona_ordinal_title"),
    (re.compile(
        r"(?i)^SESSION\s+HALL\s+OF\s+THE\s+HOUSE\s+OF\s+REPRESENTATIVES\s*$"
    ), "sona_venue"),
    (re.compile(
        r"(?i)^TO\s+THE\s+CONGRESS\b.*$"
    ), "sona_congress_line"),
    (re.compile(
        r"(?i)^ON\s+THE\s+STATE\s+OF\s+THE\s+NATION\s*$"
    ), "sona_state_line"),
    (re.compile(
        r"(?i)^OPENING\s+OF\s+THE\s+.*SESSION\b.*$"
    ), "sona_session_opening"),
    (re.compile(
        r"(?i)^PRESIDENT\s+OF\s+THE\s+PHILIPPINES\s*$"
    ), "sona_president_standalone"),
]

_SONA_LINE = [
    (re.compile(
        r"(?i)^\[DELIVERED\s+.*\]\s*$"
    ), "sona_delivery_bracket"),
    (re.compile(
        r"(?i)^FULL\s+TRANSCRIPT\s*:?\s*$"
    ), "sona_transcript_label"),
    (re.compile(
        r"(?i)^\[/?youtube\b.*\]\s*$"
    ), "sona_youtube_embed"),
    (re.compile(
        r"(?i)^VIDEO\s*:\s*$"
    ), "sona_video_label"),
    (re.compile(
        r"(?i)^\[\s*VIDEO\s+ENDS?\s*\]\s*$"
    ), "sona_video_end"),
]

_SONA_INLINE = [
    (re.compile(r"\[\s*[Aa]pplause\s*\]"), "sona_applause"),
    (re.compile(r"\[\s*[Ss]tanding\s+[Oo]vation\s*\]"), "sona_standing_ovation"),
    (re.compile(r"\[\s*[Ll]aughter\s*\]"), "sona_laughter"),
    (re.compile(r"\[\s*[Cc]heers?(?:\s+and\s+[Aa]pplause)?\s*\]"), "sona_cheers"),
    (re.compile(r"\[\s*[Mm]usic\s*\]"), "sona_music"),
    (re.compile(r"\[\s*[Cc]rowd\s+[\w\s]+?\s*\]"), "sona_crowd_reaction"),
    (re.compile(r"\[\s*[Pp]ause\s*\]"), "sona_pause"),
    (re.compile(r"(?i)[—\-–]\s*END\s*[—\-–]"), "sona_end_marker"),
    (re.compile(r"(?i)[—\-–]\s*30\s*[—\-–]"), "sona_thirty_marker"),
    (re.compile(
        r"(?i)\bUploaded\s+on\s*:\s*[\w\s,]+?\d{4}\b"
    ), "sona_uploaded_metadata"),
    (re.compile(
        r"(?i)\bPublished\s+on\s*:\s*[\w\s,]+?\d{4}\b"
    ), "sona_published_metadata"),
]

SONA_PATTERN_SET = PatternSet(
    header_patterns=_SONA_HEADER,
    header_limit=15,
    line_patterns=_SONA_LINE,
    inline_patterns=_SONA_INLINE,
    tail_patterns=[],
    tail_limit=0,
)


# Speech patterns (header_limit=5, tail_limit=0)

_SPEECH_HEADER = [
    (re.compile(
        r"(?i)^SPEECH\s+OF\s+(?:PRESIDENT|HIS\s+EXCELLENCY|HER\s+EXCELLENCY)\b.*$"
    ), "speech_title"),
    # Bracketed date/location/venue line (e.g. "[March 15, 2023, Manila Hotel]")
    (re.compile(
        r"(?i)^\[.*(?:19|20)\d{2}.*\]\s*$"
    ), "speech_date_location"),
]

_SPEECH_LINE = [
    (re.compile(
        r"(?i)^\[(?:START|END)\s+OF\s+AUDIO\s+FILE\b.*\]\s*$"
    ), "speech_audio_marker"),
]

_SPEECH_INLINE = [
    (re.compile(r"\[\s*[Aa]pplause\s*\]"), "speech_applause"),
    (re.compile(r"\[\s*[Ii]naudible\s*\]"), "speech_inaudible"),
    (re.compile(r"\[\s*[Ll]aughter\s*\]"), "speech_laughter"),
]

_SPEECH_TAIL = [
    # Source citations at end of speech transcripts
    (re.compile(
        r"(?i)^SOURCE\s*:\s*.*$"
    ), "speech_source_citation"),
    # "Retrieved from" citation lines
    (re.compile(
        r"(?i)^.*Retrieved\s+from\s+https?://.*$"
    ), "speech_retrieved_citation"),
    # Author-first citations (e.g., "Macapagal-Arroyo, G. (2005). Title...")
    (re.compile(
        r"^[A-Z][a-z]+(?:-[A-Z][a-z]+)?,\s+[A-Z]\..*\(\d{4}\)\..*$"
    ), "speech_author_citation"),
]



# Issuance patterns (header_limit=10, tail_limit=20)

_ISSUANCE_HEADER = [
    # Palace headers
    (re.compile(
        r"(?i)^MALACA[NÑ]A(?:NG|N)\s*(?:PALACE)?\s*(?:MANILA)?\s*$"
    ), "palace_header"),
    # Merged Malacañang header (906 docs): "MALACAÑANG RESIDENCE OF THE PRESIDENT OF THE PHILIPPINES MANILA"
    (re.compile(
        r"(?i)^MALACA[NÑ]A(?:NG|N)\s+RESIDENCE\s+OF\s+THE\s+PRESIDENT\b.*$"
    ), "palace_header_merged"),
    (re.compile(
        r"(?i)^RESIDENCE\s+OF\s+THE\s+PRESIDENT\b.*$"
    ), "residence_header"),
    (re.compile(
        r"(?i)^OFFICE\s+OF\s+THE\s+PRESIDENT\b.*$"
    ), "office_header"),
    (re.compile(
        r"(?i)^TANGGAPAN\s+NG\s+PANGULO\s*$"
    ), "office_header_fil"),
    (re.compile(
        r"(?i)^REPUBLIKA\s+NG\s+PILIPINAS\s*$"
    ), "republic_header_fil"),
    (re.compile(
        r"(?i)^REPUBLIC\s+OF\s+THE\s+PHILIPPINES\s*[,.]?\s*$"
    ), "republic_header"),
    # OCR-tolerant: "Republic of the Philippines" anywhere in a short scaffolding line
    (re.compile(
        r"(?i)^.{0,20}REPUBLIC\s+OF\s+THE\s+PHILIPPINES\s*[,.]?\s*$"
    ), "republic_header_ocr"),
    (re.compile(
        r"(?i)^BY\s+THE\s+PRESIDENT\s+OF\s+THE\s+PHILIPPINES\s*$"
    ), "authority_header"),
    # Location standalone
    (re.compile(
        r"(?i)^(?:MANILA|QUEZON\s+CITY),?\s*$"
    ), "location_header"),
    # Document number lines (e.g. "EXECUTIVE ORDER NO. 48", "PROCLAMATION NO. 1234-A")
    # Supports: letter suffixes (-A, -B), plural INSTRUCTIONS (1,115 LOIs),
    # hyphenated "EXECUTIVE-ORDER", series numbers (s. 2024)
    (re.compile(
        r"(?i)^(?:EXECUTIVE[\s-]+ORDER|ADMINISTRATIVE\s+ORDER|PROCLAMATION|"
        r"MEMORANDUM\s+(?:ORDER|CIRCULAR)|PRESIDENTIAL\s+DECREE|"
        r"GENERAL\s+ORDER|LETTER\s+OF\s+(?:INSTRUCTIONS?|IMPLEMENTATIONS?)|"
        r"REPUBLIC\s+ACT|SPECIAL\s+ORDER)"
        r"\s+NO\.?\s*\d+[\w\-]*\s*,?\s*(?:[Ss]\.?\s*\d+\s*)?$"
    ), "document_number"),
]

_ISSUANCE_LINE = [
    # Authority clauses
    (re.compile(
        r"(?i)^BY\s+VIRTUE\s+OF\s+THE\s+POWERS\s+VESTED\s+IN\s+ME\b.*$"
    ), "authority_clause"),
    (re.compile(
        r"(?i)^PURSUANT\s+TO\s+(?:THE\s+PROVISIONS\s+OF|SECTION)\b.*$"
    ), "authority_clause"),
    (re.compile(
        r"(?i)^IN\s+ACCORDANCE\s+WITH\b.*$"
    ), "authority_clause"),
    # Closing formulas
    (re.compile(
        r"(?i)^DONE\s+IN\s+(?:THE\s+)?(?:CITY\s+OF\s+)?(?:MANILA|QUEZON\s+CITY)\b.*$"
    ), "closing_formula"),
    # NOTE: IN WITNESS WHEREOF / THEREOF line patterns removed here
    # because they only matched the first line of a multi-line clause,
    # leaving orphan fragments like "the Republic of the Philippines to
    # be affixed." Replaced by multi-line `formulaic_witness_whereof`
    # inline pattern below (applied to joined full text).
    (re.compile(
        r"(?i)^SET\s+(?:MY\s+)?HAND\s+(?:THIS|AND)\b.*$"
    ), "closing_formula"),
    # Signature blocks (inline: "By the President: (Sgd.) NAME Title")
    (re.compile(
        r"(?i)^\(SGD\.?\)\s*.*$"
    ), "signature"),
    (re.compile(
        r"(?i)^By\s+(?:authority\s+of\s+)?the\s+President\s*:.*$"
    ), "signature"),
    (re.compile(
        r"(?i)^Executive\s+Secretary\s*$"
    ), "signature"),
    # Attestation
    (re.compile(
        r"(?i)^(?:ATTESTED|CERTIFIED|AUTHENTICATED)\s*:?\s*$"
    ), "attestation"),
    # OCR page header artifact (all-caps standalone in body)
    (re.compile(
        r"(?i)^THE\s+PRESIDENT\s+OF\s+THE\s+PHILIPPINES\s*$"
    ), "ocr_page_header"),
    # Presidential assistant / deputy secretary title lines
    (re.compile(
        r"(?i)^(?:(?:Acting\s+|Senior\s+(?:Deputy\s+)?)?Presidential\s+(?:Executive\s+)?Assistant|"
        r"(?:Acting\s+|Senior\s+)?(?:Deputy\s+)?Executive\s+Secretary|"
        r"Undersecretary|"
        r"Assistant\s+Executive\s+Secretary|"
        r"Chief\s+of\s+Staff|"
        r"Cabinet\s+Secretary|"
        r"Secretary\s+to\s+the\s+President)\s*$"
    ), "signature_title"),
    # Name + title on same line (153 docs: "JORGE B. VARGAS Secretary to the President")
    (re.compile(
        r"(?i)^[A-Z][A-Z\s.]+\s+(?:(?:Acting\s+|Senior\s+(?:Deputy\s+)?)?Executive\s+Secretary|"
        r"Secretary\s+to\s+the\s+President)\s*$"
    ), "signature_name_title"),
    # "By the Executive Secretary:" delegation line (741 proclamations)
    (re.compile(
        r"(?i)^By\s+(?:the\s+)?Executive\s+Secretary\s*:.*$"
    ), "signature_delegation"),
    # Orphaned witness fragment: "of the Republic of the Philippines to be affixed" (1,783 docs)
    (re.compile(
        r"(?i)^of\s+the\s+Republic\s+of\s+the\s+Philippines\s+to\s+be\s+affixed\b.*$"
    ), "orphaned_witness_fragment"),
    # "Immediate compliance with this Letter of Instructions is hereby enjoined" (61 docs)
    (re.compile(
        r"(?i)^Immediate\s+compliance\s+with\s+this\b.*(?:is\s+hereby\s+enjoined|enjoined)\s*\.?\s*$"
    ), "compliance_enjoined"),
    # Repealing clause body: "All laws...inconsistent...repealed or modified accordingly" (156 PDs)
    (re.compile(
        r"(?i)^All\s+(?:laws|presidential\s+decrees|executive\s+orders)"
        r".*(?:inconsistent|contrary).*(?:repealed|modified|revoked)\b.*$"
    ), "repealing_clause_body"),
    # Effectivity clauses — procedural, not policy content
    (re.compile(
        r"(?i)^(?:SEC(?:TION)?\.?\s+\d+\.?\s+)?(?:This|The\s+foregoing)\s+"
        r"(?:Executive\s+Order|Administrative\s+Order|Proclamation|"
        r"Memorandum\s+(?:Order|Circular)|Presidential\s+Decree|"
        r"Letter\s+of\s+Instruction|Order|Act)"
        r"\s+shall\s+take\s+effect\b.*$"
    ), "effectivity_clause"),
    # Separability/repealing clauses — standard legal boilerplate
    (re.compile(
        r"(?i)^(?:SEC(?:TION)?\.?\s+\d+\.?\s+)?(?:Separability|Repealing)\s+(?:Clause|Provision)\b.*$"
    ), "separability_clause"),
    (re.compile(
        r"(?i)^All\s+(?:issuances|orders|rules\s+and\s+regulations|laws|decrees|executive\s+orders)"
        r".*(?:inconsistent|contrary)\s+(?:herewith|with\s+this)\b.*$"
    ), "repealing_clause"),
    (re.compile(
        r"(?i)^Executive\s+Order\s+No\.?\s*292\s+ADMINISTRATIVE\s+CODE\b.*$"
    ), "reference_citation"),
    # Line patterns removed: "NOW THEREFORE I X President" moved to inline to preserve policy verbs
    (re.compile(
        r"(?i)^[A-Z][A-Z\s.]+President\s+of\s+the\s+Philippines\s*$"
    ), "president_name_line"),
    # Filipino institutional headers
    (re.compile(
        r"(?i)^Tanggapan\s+ng\s+Pangulo\b.*$"
    ), "filipino_header"),
    # Cadastral/land survey boilerplate (in proclamations)
    (re.compile(
        r"(?i)^All\s+corners\s+are\s+B\.?\s*L\.?\s+(?:concrete\s+)?monuments\b.*$"
    ), "cadastral_boilerplate"),
    # "Perform such other functions as may be provided by law" — catch-all duties
    (re.compile(
        r"(?i)^.*Perform\s+such\s+other\s+(?:functions|duties|related)\b.*(?:provided\s+by\s+law|assigned|delegated).*$"
    ), "catchall_duties"),
    # Dating formulas ("year of our Lord, Two Thousand...")
    (re.compile(
        r"(?i)^.*(?:year\s+of\s+(?:our|the)\s+Lord|(?:Two|One)\s+Thousand\s+and)\b.*$"
    ), "dating_formula"),
    # LOI/MO/MC "TO:" addressee lines — list of recipients, not policy
    # e.g. "TO : The Minister of Agrarian Reform", "TO: All Department Heads"
    (re.compile(
        r"(?i)^TO\s*:\s+(?:The\s+)?(?:Minister|Secretary|Director|Chairman|Head|"
        r"Commissioner|Administrator|All\s+(?:Heads|Department|Ministers|"
        r"Government|Cabinet))\b.*$"
    ), "addressee_line"),
    # Standalone recipient lines after TO: (e.g. "The Chairman, Development Bank")
    (re.compile(
        r"(?i)^The\s+(?:Minister|Secretary|Director|Chairman|Commissioner|"
        r"Administrator|Commanding|Officer)\s+(?:of|in|,)\b.*$"
    ), "addressee_continuation"),
    # "All Heads of Ministries, Bureaus..." — addressee list
    (re.compile(
        r"(?i)^All\s+Heads?\s+of\s+(?:Ministries|Departments|Bureaus|Agencies|"
        r"Offices|Government)\b.*$"
    ), "addressee_list"),
    # Section numbering labels that are purely structural
    # (e.g. "SECTION 1. Title." on its own line)
    (re.compile(
        r"(?i)^SEC(?:TION)?\.?\s+\d+\.?\s+(?:Title|Short\s+Title|"
        r"Coverage|Definition\s+of\s+Terms?|Effectivity|"
        r"Separability|Repealing)\b.*$"
    ), "section_structural"),
    # "Approved:" / "Adopted:" standalone lines (tail-like but appear mid-doc in PDs)
    (re.compile(
        r"(?i)^(?:Approved|Adopted)\s*[,:.]?\s*(?:Manila|Quezon\s+City)?\s*,?\s*"
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)?\s*\d{0,2}\s*,?\s*(?:19|20)?\d{0,2}\s*\.?\s*$"
    ), "approval_date_line"),
]

_ISSUANCE_TAIL = [
    # Source citations
    (re.compile(
        r"(?i)^SOURCE\s*:\s*.*$"
    ), "source_citation"),
    # Official Gazette bibliographic citations
    (re.compile(
        r"(?i)^OFFICE\s+OF\s+THE\s+PRESIDENT\s+OF\s+THE\s+PHILIPPINES\.\s*\(\d{4}\).*$"
    ), "gazette_citation"),
    # Malacañang Records Office variants (OCR)
    (re.compile(
        r"(?i)^MALACA[NÑ]A(?:NG|N)\s+RECORDS?\s+OFFICE\s*$"
    ), "records_office"),
    # Certified copy (OCR variants: CERTIFLED, CERTIWED, CERTLFIED, etc.)
    (re.compile(
        r"(?i)^CERT(?:IFIED|IFLED|IWED|LFIED)\s+(?:TRUE\s+)?COPY\s*:?\s*$"
    ), "certified_copy"),
    # PBBM tracking codes (e.g. PBBM001777)
    (re.compile(
        r"^PBBM\d+\s*$"
    ), "tracking_code"),
    # Pure page numbers
    (re.compile(
        r"^\d{1,3}\s*$"
    ), "page_number"),
    # Published in Official Gazette
    (re.compile(
        r"(?i)^PUBLISHED\s+IN\s+THE\s+OFFICIAL\s+GAZETTE\b.*$"
    ), "published_citation"),
    # PRRD tracking codes (e.g. "PRRD 2019-0123")
    (re.compile(
        r"^PRRD\s*\d[\d\s\-]+\s*$"
    ), "tracking_code_prrd"),
    # Director title lines (e.g. "DIRECTOR IV")
    (re.compile(
        r"^DIRECTOR\s+(?:IV|III|II|I|V)\s*$"
    ), "tail_director"),
    # ATTY. lines (e.g. "ATTY. JUAN DELA CRUZ")
    (re.compile(
        r"^ATTY\.\s+.*$"
    ), "tail_attorney"),
    # Reference : Annex lines
    (re.compile(
        r"(?i)^REFERENCE\s*:\s*ANNEX\b.*$"
    ), "reference_annex"),
    # Author-first citations (e.g. "Smith, J. (2004). Title...")
    (re.compile(
        r"^[A-Z][a-z]+,\s+[A-Z]\..*\(\d{4}\)\..*$"
    ), "author_citation"),
    # Bureau of Printing bibliographic citation (356 EOs/AOs)
    (re.compile(
        r"(?i)^Bureau\s+of\s+Printing\.\s*\(\d{4}\)\..*$"
    ), "bureau_printing_citation"),
    # Standalone "Manila, Month Day, Year" date stamp (2,382 MOs/MCs)
    (re.compile(
        r"(?i)^(?:Manila|Quezon\s+City)\s*,\s*"
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2}\s*,?\s*\d{4}\s*\.?\s*$"
    ), "manila_date_stamp"),
    # Self-citation tail: "Administrative Order No. 63, July 23, 1948"
    (re.compile(
        r"(?i)^(?:Administrative\s+Order|Executive\s+Order|Presidential\s+Decree|"
        r"Memorandum\s+(?:Order|Circular)|Letter\s+of\s+Instructions?)"
        r"\s+No\.?\s*\d+[\w\-]*\s*,\s*"
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2}\s*,?\s*\d{4}\s*$"
    ), "self_citation_tail"),
    # "For compliance" standalone closing (e.g. "For compliance, JUL 15 1996")
    (re.compile(
        r"(?i)^For\s+(?:strict\s+|immediate\s+)?compliance\b.*$"
    ), "for_compliance_standalone"),
]

# Issuance inline patterns — substring removal of formulaic legal phrases
# that would otherwise anchor embeddings to shared scaffolding.

_ISSUANCE_INLINE = [
    (re.compile(
        r"(?i)\bupon\s+(?:the\s+)?recommendation\s+of\s+"
        r"(?:the\s+)?[\w\s,.\-]{3,80}?"
        r"(?=\s*(?:,\s*and|\s+and\s+(?:by|pursuant)|,\s*pursuant|\s*,?\s*(?:I|do\s+hereby|the\s+President)|\.)|"
        r"\s*,\s*(?:do|I|set|reserve|withdraw|hereby))",
    ), "formulaic_recommendation"),
    (re.compile(
        r"(?i),?\s*(?:and\s+)?pursuant\s+to\s+(?:the\s+)?"
        r"(?:authority|powers?|provisions?)\s+vested\s+in\s+me\s+by\s+law,?",
    ), "formulaic_authority_vested"),
    (re.compile(
        r"(?i),?\s*(?:and\s+)?by\s+(?:the\s+)?powers?\s+vested\s+in\s+me"
        r"(?:\s+by\s+(?:the\s+Constitution|law)(?:\s+and\s+[\w\s]+?)?)?",
    ), "formulaic_by_powers_vested"),
    (re.compile(
        r"(?i),?\s*(?:and\s+)?pursuant\s+to\s+(?:the\s+provisions?\s+of\s+)?"
        r"(?:Section|Article)\s+\d+[\w\-]*"
        r"(?:\s*,?\s*(?:paragraph|subsection)\s+[\w\(\)]+)*"
        r"(?:\s+of\s+(?:Republic\s+Act|Executive\s+Order|Presidential\s+Decree|"
        r"Commonwealth\s+Act|Batas\s+Pambansa)\s+(?:No\.?\s*)?\d+\w*"
        r"(?:\s*,?\s*(?:as\s+amended|otherwise\s+known)[^,;.]*)*)?",
    ), "formulaic_legal_citation"),
    (re.compile(
        r"(?i)I,\s+[A-Z][A-Za-z\s.\-]+?,\s+President\s+of\s+the\s+"
        r"(?:Philippines|Republic\s+of\s+the\s+Philippines)\s*,?\s*"
        r"do\s+hereby",
    ), "formulaic_presidential_declaration"),
    # Truncated declaration after partial stripping — anchors embeddings to shared scaffolding
    (re.compile(
        r"(?i)\bI,\s+[A-Z][A-Za-z\s.\-]{2,60}?,\s+(?:Acting\s+)?President\s+of\s+the\s+"
        r"(?:Philippines|Republic\s+of\s+the\s+Philippines)\s*,?\s*"
        r"(?:and\s+(?:decree|direct|order|proclaim|declare|ordain)[s]?\s*:?|:)",
    ), "formulaic_presidential_declaration_truncated"),
    (re.compile(
        r"(?i)\bdo\s+hereby\s+(?:order|declare|direct|proclaim|ordain|decree)",
    ), "formulaic_hereby_verb"),
    # Amendment headers have pure structural text, no policy content
    (re.compile(
        r"(?i)\bAMENDING\s+(?:SECTION|ARTICLE|SUBSECTION)\s+[\w\-]+(?:\s*,?\s*"
        r"(?:(?:AND|OR)\s+[\w\-]+))*"
        r"(?:\s+OF\s+(?:THE\s+)?"
        r"(?:EXECUTIVE|MEMORANDUM|ADMINISTRATIVE|GENERAL|SPECIAL)\s+ORDER"
        r"(?:\s+NO\.?\s*[\w\-]+)?(?:\s*,?\s*SERIES\s+OF\s+\d+)?)?",
    ), "formulaic_amending_section"),
    (re.compile(
        r"(?i)\bSection\s+\d+[\w\-]*\.\s*[^.]{0,200}?"
        r"(?:is|are)\s+hereby\s+amended\s+to\s+read\s+as\s+follows",
    ), "formulaic_section_hereby_amended"),
    # Strip label only, topic text remains
    (re.compile(
        r"(?i)^\s*SUBJECT\s*:\s*",
    ), "formulaic_subject_label"),
    (re.compile(
        r"(?i)\bRepublic\s+of\s+the\s+Philippines\s+Congress\s+of\s+the\s+"
        r"Philippines\s+Metro\s+Manila\b",
    ), "formulaic_ra_preamble"),
    (re.compile(
        r"(?i)^\s*AN\s+ACT\s+",
    ), "formulaic_an_act_preamble"),
    (re.compile(
        r"(?i)for\s+(?:the\s+)?(?:information|guidance|compliance)"
        r"(?:\s+and\s+(?:information|guidance|compliance))?"
        r"\s+of\s+all\s+concerned"
        r"(?:\s+and\s+for\s+(?:strict|immediate|faithful)\s+compliance)?",
    ), "formulaic_guidance_closing"),
    (re.compile(
        r"(?i)\bfor\s+(?:strict|immediate|faithful)\s+compliance\b",
    ), "formulaic_compliance_closing"),
    (re.compile(
        r"(?i),?\s*by\s+virtue\s+of\s+the\s+powers?\s+vested\s+in\s+me"
        r"(?:\s+by\s+(?:the\s+Constitution|law)(?:\s+and\s+[\w\s]+?)?)?(?=\s*,)",
    ), "formulaic_virtue_powers"),
    (re.compile(
        r"(?i)it\s+is\s+but\s+fitting\s+(?:and\s+proper\s+)?that\s+.*?"
        r"(?:be\s+given\s+(?:full\s+)?opportunity\s+to\s+celebrate|"
        r"celebrate\s+the\s+occasion)",
    ), "formulaic_fitting_proper"),
    (re.compile(
        r"(?i),?\s*subject\s+to\s+(?:community\s+quarantine|social\s+distancing|"
        r"public\s+health\s+measures?)(?:\s*,?\s*(?:and\s+)?(?:other\s+)?"
        r"(?:community\s+quarantine|social\s+distancing|public\s+health\s+measures?))*",
    ), "formulaic_covid_qualifier"),
    (re.compile(
        r"(?i)(?:The\s+)?participants?\s+shall\s+submit\s+.*?"
        r"report\s+on\s+their\s+(?:attendance|participation)",
    ), "formulaic_attendance_report"),
    # Land proclamation template patterns — were creating dominant catch-all topic
    (re.compile(
        r"(?i)(?:a\s+)?(?:certain\s+)?(?:following\s+)?"
        r"parcels?\s+(?:of\s+land\s+)?of\s+the\s+public\s+domain"
        r"(?:\s*,?\s*situated\s+(?:in|at))?",
    ), "formulaic_parcel_public_domain"),
    (re.compile(
        r"(?i)(?:more\s+)?particularly\s+described\s+"
        r"(?:as\s+follows|hereunder|below|herein|in\s+the\s+[\w\s]+?)?[\s:,.]*",
    ), "formulaic_particularly_described"),
    (re.compile(
        r"(?i),?\s*subject\s+to\s+(?:any\s+)?private\s+rights?"
        r"(?:\s*,?\s*if\s+any(?:\s+there\s+be)?)?",
    ), "formulaic_private_rights"),
    (re.compile(
        r"(?i),?\s*(?:and\s+)?(?:subject\s+)?to\s+any\s+and\s+all\s+rights\s+"
        r"(?:and\s+privileges\s+)?(?:of\s+[\w\s,]+?)?(?=[.;]|$)",
    ), "formulaic_rights_privileges"),
    (re.compile(
        r"(?i),?\s*containing\s+an?\s+(?:aggregate\s+)?area\s+of\s+[\w\s,.()]+?"
        r"(?:hectares?|square\s+meters?|sq(?:\.|uare)?\s*m(?:eters?|\.?)?|ha\b)"
        r"(?:\s*,?\s*more\s+or\s+less)?",
    ), "formulaic_area_hectares"),
    (re.compile(
        r"(?i)withdraw\s+from\s+sale"
        r"(?:\s*,?\s*(?:entry|disposition|settlement))*"
        r"(?:\s+and\s+reserve(?:\s+the\s+same)?)?"
        r"(?:\s+for\s+[\w\s,]+?\s+purposes?)?",
    ), "formulaic_withdraw_reserve"),
    (re.compile(
        r"(?i)\breserve\s+(?:the\s+same\s+)?for\s+[\w\s,]{3,60}?\s+purposes?\b",
    ), "formulaic_reserve_for_purposes"),
    (re.compile(
        r"(?i)set\s+aside\s+(?:a\s+)?(?:certain\s+)?parcel(?:s)?\s+of\s+land",
    ), "formulaic_set_aside_parcel"),
    (re.compile(
        r"(?i)\bestablish\s+the\s+[\w\s]+?\s+"
        r"(?:Forest|Military|National|Watershed|Marine|Game)\s+"
        r"(?:Reserve|Reservation|Park|Sanctuary)\b",
    ), "formulaic_establish_reserve"),
    (re.compile(
        r"(?i),?\s*(?:and\s+)?place\s+(?:it|them|the\s+same)\s+under\s+the\s+"
        r"administration\s+(?:and\s+control\s+)?of\s+[\w\s,]+?(?=[.;,]|\s+for\s+|\s+which)",
    ), "formulaic_place_under_admin"),
    (re.compile(
        r"(?i)under\s+the\s+administration\s+(?:and\s+control\s+)?of\s+"
        r"the\s+(?:Bureau|Department|Director|Ministry|Office)\s+of\s+[\w\s,]+?"
        r"(?=[,.;]|\s+subject|\s+which|\s+for)",
    ), "formulaic_bureau_administration"),
    (re.compile(
        r"(?i),?\s*(?:and\s+)?to\s+any\s+and\s+all\s+rights"
        r"(?:\s+granted\s+or\s+reserved\s+to\s+citizens?)?"
        r"(?:\s+by\s+[\w\s,]+?)?(?=[.;]|$)",
    ), "formulaic_rights_citizens"),
    (re.compile(
        r"(?i)Act\s+of\s+Congress\s+of\s+\w+\s+\w+,\s+nineteen\s+hundred(?:\s+\w+)*",
    ), "formulaic_act_of_congress"),
    (re.compile(
        r"(?i),?\s*known\s+as\s+the\s+[\w\s]+?\s+"
        r"(?:Code|Act|Law|Act\s+of\s+\d{4})",
    ), "formulaic_known_as_code"),
    (re.compile(
        r"(?i)(?:section|Act)\s+Numbered\s+[\w\s\-]+?\s+hundred"
        r"(?:\s+and\s+[\w\s\-]+?)?",
    ), "formulaic_spelled_number"),
    (re.compile(
        r"(?i)Bounded\s+on\s+the\s+(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West)[\w\s.,;-]+?"
        r"(?:by\s+(?:Lot|line|Road|Creek|River|lot))[^;.]*",
    ), "formulaic_cadastral_bounded"),
    (re.compile(
        r"(?i)(?:Bureau\s+of\s+Lands\s+)?[Pp]lan\s+(?:Swo|Psu|Pcs|Bsd|CAD|Cad)[\s-]?[\w-]+",
    ), "formulaic_survey_plan"),
    (re.compile(
        r"(?i)Lot\s+No\.\s*\d+[\w-]*",
    ), "formulaic_lot_number"),
    (re.compile(
        r"(?i)thence\s+[NSEW]\s*\d+[°\s-]\s*\d*[°\-]?\s*\d*\s*[NSEW]?\s*\d+(?:\.\d+)?\s*m(?:eters)?\.?",
    ), "formulaic_bearing_distance"),
    (re.compile(
        r"(?i)pursuant\s+to\s+(?:the\s+provisions\s+of\s+)?Chapter\s+[IVX\d]+\s+"
        r"of\s+the\s+Public\s+Land\s+(?:Law|Act)(?:\s*\(Act\s+No\.?\s*\d+\))?",
    ), "formulaic_public_land_chapter"),
    (re.compile(
        r"(?i)under\s+the\s+administration\s+of\s+the\s+Director\s+of\s+[\w\s]+?(?=,|\.|\s+subject)",
    ), "formulaic_director_admin"),
    # WHEREAS clause: strip entire clause to expose operative content for topic modeling
    (re.compile(
        r"(?i)\bWHEREAS\s*,\s*[^;]{0,2000}?;\s*",
    ), "formulaic_whereas_clause"),
    (re.compile(
        r"(?i)(?:^|[;.\n])\s*WHEREAS\s*,\s*",
    ), "formulaic_whereas_marker"),
    (re.compile(
        r"(?i)(?:^|[;.\n])\s*NOW,?\s+THEREFORE,?\s*",
    ), "formulaic_now_therefore"),
    (re.compile(
        r"(?i)\bDONE\s+in\s+the\s+City\s+of\s+"
        r"(?:Manila|Quezon\s+City|Cebu|Davao|Baguio|Malaca\w+)"
        r"[\s\S]{0,600}?"
        r"(?:President\s+of\s+the\s+Philippines|\.(?=\s*$))",
    ), "formulaic_signature_block"),
    (re.compile(
        r"(?i)\bIN\s+WITNESS\s+WHEREOF[\s\S]{0,400}?"
        r"(?:affixed|affix|caused\s+the\s+seal)[\s\S]{0,200}?\.",
    ), "formulaic_witness_whereof"),
    (re.compile(
        r"(?i)\bBy\s+(?:the\s+)?authority\s+of\s+the\s+President\b",
    ), "formulaic_by_authority"),
    # Speech formalities (also merged into SPEECH_PATTERN_SET)
    (re.compile(
        r"(?i)\bladies\s+and\s+gentlemen\b[\s,.:;]*",
    ), "formulaic_ladies_gentlemen"),
    (re.compile(
        r"(?i)\bmy\s+(?:fellow|beloved|dear)\s+(?:Filipinos?|countrymen|citizens?|"
        r"compatriots?|people)\b[\s,.:;]*",
    ), "formulaic_fellow_filipinos"),
    (re.compile(
        r"(?i)\bgood\s+(?:morning|afternoon|evening|day)(?:\s+to\s+(?:all\s+of\s+)?you)?\b[\s,.:;]*",
    ), "formulaic_good_morning"),
    (re.compile(
        r"(?i)\bthank\s+you(?:\s+very\s+much)?(?:\s+and\s+good\s+\w+)?\b[\s,.:;]*",
    ), "formulaic_thank_you"),
    (re.compile(
        r"(?i)\bmagandang\s+(?:umaga|hapon|gabi|araw)(?:\s+po)?\b[\s,.:;]*",
    ), "formulaic_magandang_greeting"),
    (re.compile(
        r"(?i)\bmabuhay(?:\s+ang\s+[\w\s]+)?[!\.]?\b",
    ), "formulaic_mabuhay"),
    # Uses ` ` not \s to prevent greedy cross-paragraph matching
    (re.compile(
        r"(?i)\b(?:His|Her)\s+Excellency\s+(?:President\s+)?[A-Z][\w. \-]+",
    ), "formulaic_excellency"),
    (re.compile(
        r"(?i)\b(?:The\s+)?Honorable\s+[A-Z][\w. ,\-]+?(?=[;.]|\s+and\s+)",
    ), "formulaic_honorable"),
    (re.compile(
        r"(?i)\bmembers\s+of\s+the\s+(?:Cabinet|Senate|Congress|House|"
        r"diplomatic\s+corps|Armed\s+Forces)\b[\s,.:;]*",
    ), "formulaic_members_of"),
    (re.compile(
        r"(?i)\bfellow\s+workers\s+in\s+(?:government|the\s+government)\b[\s,.:;]*",
    ), "formulaic_fellow_workers"),
    (re.compile(
        r"(?i)\b(?:let\s+me\s+begin\s+by|in\s+closing|before\s+I\s+(?:conclude|end))\b[\w\s,]*?(?=[.;]|$)",
    ), "formulaic_speech_transition"),
    (re.compile(
        r"(?i)\b(?:warm|cordial|heartfelt|very\s+warm)\s+welcome\b[\s,.:;]*",
    ), "formulaic_warm_welcome"),
    (re.compile(
        r"(?i)\bwelcome\s+(?:to\s+(?:you\s+)?(?:all|everyone|our)|you(?:\s+all)?)\b[\s,.:;]*",
    ), "formulaic_welcome"),
    (re.compile(
        r"(?i)\bthank\s+you\s+(?:all\s+)?for\s+(?:the\s+|your\s+)?(?:warm|kind|generous|gracious)\s+welcome\b[\s,.:;]*",
    ), "formulaic_thank_welcome"),
    (re.compile(
        r"(?i)\b(?:congratulations|my\s+congratulations|warmest\s+congratulations)\s+(?:to|go\s+out\s+to|are\s+(?:in\s+)?order)\b[\w\s,]*?(?=[.;]|$)",
    ), "formulaic_congratulations"),
    (re.compile(
        r"(?i)\bI\s+(?:wish\s+to\s+)?congratulate\s+\w[\w\s,'\-]{0,80}?(?=\s+(?:for|on)\s+|[.;])",
    ), "formulaic_i_congratulate"),
    (re.compile(
        r"(?i)\b(?:it\s+is\s+(?:indeed\s+)?my\s+(?:great\s+|distinct\s+|singular\s+|special\s+)?(?:honor|privilege)|what\s+an\s+honor|I\s+am\s+(?:deeply\s+|truly\s+|greatly\s+|humbled\s+and\s+)?honored)\b[\w\s,]*?(?=[.;]|$)",
    ), "formulaic_honor_opener"),
    (re.compile(
        r"(?i)\b(?:it\s+is\s+(?:indeed\s+)?(?:a\s+|my\s+|our\s+)?(?:great\s+|real\s+|rare\s+|special\s+|distinct\s+)?pleasure|it\s+(?:gives|brings)\s+me\s+(?:great\s+)?pleasure|I\s+am\s+(?:deeply\s+|truly\s+|most\s+)?pleased)\b[\w\s,]*?(?=[.;]|$)",
    ), "formulaic_pleasure_opener"),
    (re.compile(
        r"(?i)\bdistinguished\s+(?:guests?|delegates?|friends?|members?|colleagues?|fellows?|participants?|visitors?|officials?|excellencies)\b[\s,.:;]*",
    ), "formulaic_distinguished"),
    (re.compile(
        r"(?i)\bon\s+behalf\s+of\s+(?:the\s+|our\s+)?[\w\s,'\-]{1,80}?(?=[,.;]|\s+I\s+|\s+we\s+)",
    ), "formulaic_on_behalf"),
    (re.compile(
        r"(?i)\byour\s+excellenc(?:y|ies)\b[\s,.:;]*",
    ), "formulaic_your_excellency"),
    (re.compile(
        r"(?i)\b(?:allow|permit)\s+me\s+to\s+\w[\w\s,'\-]{0,60}?(?=[.;]|$)",
    ), "formulaic_allow_me"),
    (re.compile(
        r"(?i)\bI\s+(?:would\s+like\s+to|wish\s+to|want\s+to)\s+thank\s+\w[\w\s,'\-]{0,80}?(?=[.;]|$)",
    ), "formulaic_i_would_thank"),
    (re.compile(
        r"(?i)\bgreetings(?:\s+to\s+(?:you\s+)?(?:all|everyone))?\b[\s,.:;]*",
    ), "formulaic_greetings"),
    (re.compile(
        r"(?i)\bwith\s+(?:great\s+|deep\s+|utmost\s+)?(?:pride|joy|pleasure|humility|gratitude)\b[\s,.:;]*",
    ), "formulaic_with_pride"),
    (re.compile(
        r"(?i)\b(?:good|glad|happy|delighted|pleased)\s+to\s+be\s+(?:here|with\s+you|back)\b[\w\s,]*?(?=[.;]|$)",
    ), "formulaic_good_to_be_here"),
    (re.compile(
        r"(?i)^hello\b[\s.!,]*",
    ), "formulaic_hello_opener"),
]

ISSUANCE_PATTERN_SET = PatternSet(
    header_patterns=_ISSUANCE_HEADER,
    header_limit=10,
    line_patterns=_ISSUANCE_LINE,
    inline_patterns=_ISSUANCE_INLINE,
    tail_patterns=_ISSUANCE_TAIL,
    tail_limit=25,
)

_SPEECH_FORMALITY_NAMES = {
    "formulaic_ladies_gentlemen",
    "formulaic_fellow_filipinos",
    "formulaic_good_morning",
    "formulaic_thank_you",
    "formulaic_magandang_greeting",
    "formulaic_mabuhay",
    "formulaic_excellency",
    "formulaic_honorable",
    "formulaic_members_of",
    "formulaic_fellow_workers",
    "formulaic_speech_transition",
    "formulaic_warm_welcome",
    "formulaic_welcome",
    "formulaic_thank_welcome",
    "formulaic_congratulations",
    "formulaic_i_congratulate",
    "formulaic_honor_opener",
    "formulaic_pleasure_opener",
    "formulaic_distinguished",
    "formulaic_on_behalf",
    "formulaic_your_excellency",
    "formulaic_allow_me",
    "formulaic_i_would_thank",
    "formulaic_greetings",
    "formulaic_with_pride",
    "formulaic_good_to_be_here",
    "formulaic_hello_opener",
}
_SPEECH_FORMALITY_PATTERNS = [
    (pat, name) for pat, name in _ISSUANCE_INLINE
    if name in _SPEECH_FORMALITY_NAMES
]
SPEECH_PATTERN_SET = PatternSet(
    header_patterns=_SPEECH_HEADER,
    header_limit=5,
    line_patterns=_SPEECH_LINE,
    inline_patterns=_SPEECH_INLINE + _SPEECH_FORMALITY_PATTERNS,
    tail_patterns=_SPEECH_TAIL,
    tail_limit=10,
)


# Republic Act patterns (header_limit=20, tail_limit=30)

_RA_HEADER = _ISSUANCE_HEADER + [
    # Bill numbers (e.g. "H. NO. 1234", "S. NO. 567")
    (re.compile(
        r"(?i)^[HS]\.\s*NO\.\s*\d+\s*$"
    ), "ra_bill_number"),
    (re.compile(
        r"(?i)^CONGRESS\s+OF\s+THE\s+PHILIPPINES\s*$"
    ), "ra_congress"),
    # Ordinal Congress (e.g. "SEVENTEENTH CONGRESS")
    (re.compile(
        r"(?i)^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|"
        r"NINTH|TENTH|ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|"
        r"SIXTEENTH|SEVENTEENTH|EIGHTEENTH|NINETEENTH|TWENTIETH)\s+CONGRESS\s*$"
    ), "ra_ordinal_congress"),
    # Session line (e.g. "FIRST REGULAR SESSION", "THIRD SPECIAL SESSION")
    (re.compile(
        r"(?i)^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)?\s*"
        r"(?:REGULAR|SPECIAL)\s*SESSION\s*$"
    ), "ra_session"),
    (re.compile(
        r"(?i)^BEGUN\s+AND\s+HELD\s+IN\b.*$"
    ), "ra_begun_held"),
    (re.compile(
        r"(?i)^METRO\s+MANILA\s*$"
    ), "ra_metro_manila"),
    (re.compile(
        r"(?i)^BE\s+IT\s+ENACTED\s+BY\s+THE\s+SENATE\b.*$"
    ), "ra_enacting_clause"),
    # Bracketed RA number (e.g. "[REPUBLIC ACT NO. 12345]")
    (re.compile(
        r"(?i)^\[\s*REPUBLIC\s+ACT\s+NO\.\s*\d+\s*\]\s*$"
    ), "ra_bracketed_number"),
    # OCR-tolerant bracketed RA number (trailing chars, OCR artifacts)
    (re.compile(
        r"(?i)^\[?\s*REPUBLIC\s+ACT\s+NO\.?\s*\d+[\w\-]*\s*\]?\s*[,.]?\s*$"
    ), "ra_bracketed_number_ocr"),
    # OCR-tolerant Metro Manila (may have leading/trailing OCR chars)
    (re.compile(
        r"(?i)^.{0,10}METRO\s+MANILA\s*[,.]?\s*$"
    ), "ra_metro_manila_ocr"),
    # OCR-tolerant ordinal Congress (may merge with trailing text)
    (re.compile(
        r"(?i)^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|"
        r"NINTH|TENTH|ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|"
        r"SIXTEENTH|SEVENTEENTH|EIGHTEENTH|NINETEENTH|TWENTIETH)\s+"
        r"CONGRESS\s+OF\s+THE\s+PHILIPPINES\s*[,.]?\s*$"
    ), "ra_ordinal_congress_full"),
    # OCR-tolerant session line (e.g. "First Regular Session,")
    (re.compile(
        r"(?i)^(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+"
        r"(?:REGULAR|SPECIAL)\s+SESSION\s*[,.]?\s*$"
    ), "ra_session_ocr"),
    # Ordinal date line (e.g. "day of June, two thousand twenty-three")
    (re.compile(
        r"(?i)^.{0,30}day\s+of\s+\w+\s*,?\s*two\s+thousand\b.*$"
    ), "ra_ordinal_date"),
    # "held in (the City of) Manila/Quezon City, on (Monday|...)"
    (re.compile(
        r"(?i)^(?:BEGUN\s+AND\s+)?HELD\s+IN\b.*(?:MANILA|QUEZON\s+CITY)\b.*$"
    ), "ra_held_in"),
    # "on (Monday|...), the Nth day of Month"
    (re.compile(
        r"(?i)^ON\s+(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY)\b.*$"
    ), "ra_on_weekday"),
    # House Bill number line (e.g. "[H. No. 8243]")
    (re.compile(
        r"(?i)^\[?\s*(?:H|S)\.?\s*(?:B\.?\s*)?NO\.?\s*\d+\s*\]?\s*[,.]?\s*$"
    ), "ra_bill_number_ocr"),
]

_RA_TAIL = _ISSUANCE_TAIL + [
    # Approved line (e.g. "APPROVED, June 12, 2023")
    (re.compile(
        r"(?i)^APPROVED\s*[,:.]\s*.*$"
    ), "ra_approved"),
    (re.compile(
        r"(?i)^PRESIDENT\s+OF\s+THE\s+SENATE\s*$"
    ), "ra_senate_president"),
    (re.compile(
        r"(?i)^SPEAKER\s+OF\s+THE\s+HOUSE\b.*$"
    ), "ra_speaker"),
    (re.compile(
        r"(?i)^(?:OF\s+)?REPRESENTATIVES\s*$"
    ), "ra_representatives"),
    (re.compile(
        r"(?i)^SECRETARY\s+(?:OF\s+THE\s+SENATE|GENERAL)\b.*$"
    ), "ra_secretary"),
    (re.compile(
        r"(?i)^THIS\s+ACT\s+WHICH\s+ORIGINATED\b.*$"
    ), "ra_origination"),
    (re.compile(
        r"(?i)^WAS\s+(?:FINALLY\s+)?PASSED\s+BY\b.*$"
    ), "ra_passed"),
    (re.compile(
        r"(?i)^LAPSED\s+INTO\s+LAW\b.*$"
    ), "ra_lapsed"),
]

REPUBLIC_ACT_PATTERN_SET = PatternSet(
    header_patterns=_RA_HEADER,
    header_limit=20,
    line_patterns=_ISSUANCE_LINE,
    inline_patterns=_ISSUANCE_INLINE,
    tail_patterns=_RA_TAIL,
    tail_limit=30,
)


ALL_PATTERN_SET = PatternSet(
    header_patterns=_SONA_HEADER + _SPEECH_HEADER + _RA_HEADER,
    header_limit=20,  # max across categories
    line_patterns=_SONA_LINE + _SPEECH_LINE + _ISSUANCE_LINE,
    inline_patterns=_SONA_INLINE + _SPEECH_INLINE + _ISSUANCE_INLINE,
    tail_patterns=_RA_TAIL + _SPEECH_TAIL,
    tail_limit=30,
)


def _get_pattern_set(category: str) -> PatternSet:
    if category == "sona":
        return SONA_PATTERN_SET
    elif category == "speech":
        return SPEECH_PATTERN_SET
    elif category == "republic_act":
        return REPUBLIC_ACT_PATTERN_SET
    elif category == "all":
        return ALL_PATTERN_SET
    else:
        return ISSUANCE_PATTERN_SET


# Heuristic garbage detection — font-shifted OCR, garbled OCR, web noise.

# Spaced-out OCR letters: "O F F I C E", "P R O J E C T"
_SPACED_LETTERS_RE = re.compile(r"^([A-Z]\s+){3,}[A-Z]?\s*$")

# ChanRobles Virtual Law Library scraping artifacts
_CHANROBLES_RE = re.compile(
    r"(?i)^(?:ChanRobles|Chan\s+Robles|Virtual\s+Law\s+Library|"
    r"www\.chanrobles\.com|PLEASE\s+CLICK\s+HERE\s+FOR\s+THE\s+LATEST|"
    r"Home\s*>|collection\s+of\s+Philippine\s+laws|"
    r"main\s+indices|Search\s+for)\b.*$"
)

# LawPhil Project scraping artifacts (garbled Unicode watermarks)
# Variants: "1aшphi1", "ℒαwρhi৷", "The Lawphil Project - Arellano Law Foundation"
_LAWPHIL_RE = re.compile(
    r"(?i)^(?:1a\u0448phi1|"                           # 1aшphi1
    r"\u2112\u03b1w\u03c1hi\u09f7|"                    # ℒαwρhi৷
    r"The\s+Lawphil\s+Project\b.*|"                    # footer text
    r"Arellano\s+Law\s+Foundation\b.*|"                # foundation attribution
    r"lawphil\.net\b.*"                                # URL artifact
    r")$"
)

# (ORIGINAL MISSING) marker on documents with lost originals
_ORIGINAL_MISSING_RE = re.compile(
    r"(?i)^\(?\s*ORIGINAL\s+MISSING\s*\)?\s*$"
)

# Standalone page numbers anywhere (broader than tail-only)
_PAGE_NUMBER_RE = re.compile(r"^\d{1,3}\s*$")


def _is_font_shifted(line: str) -> bool:
    """Detect font-shifted OCR via vowel ratio (<23% = shifted)."""
    n = len(line)
    alpha_count = sum(1 for c in line if c.isalpha())
    digit_count = sum(1 for c in line if c.isdigit())

    # Pure digit+punct garbage
    if n >= 5 and alpha_count == 0 and digit_count > n * 0.3:
        return True

    # Alpha text with abnormally low vowel ratio
    if n < 15:
        return False
    if alpha_count < n * 0.5:
        return False
    vowels = sum(1 for c in line if c.lower() in "aeiou")
    vowel_ratio = vowels / alpha_count
    return vowel_ratio < 0.23


def _is_garbled_ocr(line: str) -> bool:
    """Detect garbled OCR via noise character ratio (>10% = garbled)."""
    if len(line) < 15:
        return False
    noise = sum(1 for c in line if c in ";{}[]|^~<>")
    return noise > len(line) * 0.1


def _classify_garbage(line: str) -> str | None:
    """Return a garbage tag if line is noise, else None."""
    if _PAGE_NUMBER_RE.match(line):
        return "page_number"
    if _SPACED_LETTERS_RE.match(line):
        return "ocr_spaced_letters"
    if _CHANROBLES_RE.match(line):
        return "web_scraping_noise"
    if _LAWPHIL_RE.match(line):
        return "web_scraping_noise"
    if _ORIGINAL_MISSING_RE.match(line):
        return "original_missing_marker"
    if _is_font_shifted(line):
        return "ocr_font_shifted"
    if _is_garbled_ocr(line):
        return "ocr_garbled"
    return None


# Cadastral survey description stripping.

_CADASTRAL_START = re.compile(
    r"(?:"
    r"A\s+(?:PARCEL|parcel)\s+(?:OF|of)\s+(?:LAND|land)[,\s]+(?:bounded|situated|\()"
    r"|"
    r"[Bb]eginning\s+at\s+a\s+point\s+marked"
    r")",
)

_CADASTRAL_END = re.compile(
    r"(?:containing\s+an\s+area\s+of|SQUARE\s+METERS|square\s+meters"
    r"|hectares?\s*[.,]|point\s+of\s+beginning)",
    re.IGNORECASE,
)

_HAS_COORDINATES = re.compile(
    r"(?:thence\s+[NS]|deg\.\s*\d|[NS]\.\s*\d+\s*°|BLLM|B\.L\.L\.M|Cad\.\s*\d|Psd-\d|Swo-)"
)


def _strip_cadastral(text: str) -> str:
    """Remove survey coordinate blocks, preserving policy preamble."""
    if not _HAS_COORDINATES.search(text):
        return text

    result = text
    # Some proclamations have multiple parcels; cap iterations as a safety net.
    for _ in range(20):
        match = _CADASTRAL_START.search(result)
        if not match:
            break

        start = match.start()

        end_match = _CADASTRAL_END.search(result, match.end())
        if end_match:
            end = end_match.end()
            # extend to end-of-line so we don't leave a half-stripped line
            newline_after = result.find("\n", end)
            if newline_after != -1:
                end = newline_after
        else:
            # no clear end marker — cut to EOF
            end = len(result)

        result = result[:start].rstrip() + "\n" + result[end:].lstrip()

    return result


def _strip(text: str, category: str) -> BoilerplateResult:
    """Multi-pass boilerplate removal — header/tail/line/heuristic/inline/cadastral."""
    original_len = len(text)
    removed: list[str] = []
    ps = _get_pattern_set(category)

    # nbsp from OCR
    if "\xa0" in text:
        text = text.replace("\xa0", " ")
        removed.append("nbsp_normalized")

    # form-feed page breaks (474 docs)
    if "\x0c" in text:
        text = text.replace("\x0c", "\n")
        removed.append("formfeed_stripped")

    lines = text.split("\n")
    total = len(lines)

    remove_indices: set[int] = set()

    # Pass 1 — header patterns (first N lines only)
    header_end = min(ps.header_limit, total)
    for i in range(header_end):
        stripped = lines[i].strip()
        for pattern, name in ps.header_patterns:
            if pattern.match(stripped):
                remove_indices.add(i)
                removed.append(name)
                break

    # Pass 2 — tail patterns (last N lines only)
    if ps.tail_limit > 0 and total > 0:
        tail_start = max(0, total - ps.tail_limit)
        for i in range(tail_start, total):
            if i in remove_indices:
                continue
            stripped = lines[i].strip()
            for pattern, name in ps.tail_patterns:
                if pattern.match(stripped):
                    remove_indices.add(i)
                    removed.append(name)
                    break

    # Pass 3 — line patterns anywhere (whole-line removal)
    for i in range(total):
        if i in remove_indices:
            continue
        stripped = lines[i].strip()
        for pattern, name in ps.line_patterns:
            if pattern.match(stripped):
                remove_indices.add(i)
                removed.append(name)
                break

    # Pass 4 — heuristic garbage detection
    for i in range(total):
        if i in remove_indices:
            continue
        stripped = lines[i].strip()
        if not stripped:
            continue
        tag = _classify_garbage(stripped)
        if tag:
            remove_indices.add(i)
            if tag not in removed:
                removed.append(tag)

    surviving = [
        lines[i] for i in range(total) if i not in remove_indices
    ]

    # Pass 5a — paragraph-level drop. Threshold of 5 distinct matches preserves
    # operative clauses (typically 3-4 matches) while killing pure scaffolding.
    PARA_DROP_THRESHOLD = 5
    if ps.inline_patterns:
        joined = "\n".join(surviving)
        paragraphs = re.split(r"\n\s*\n", joined)
        kept_paragraphs: list[str] = []
        dropped_any = False
        for para in paragraphs:
            if not para.strip():
                kept_paragraphs.append(para)
                continue
            matched_names: set[str] = set()
            for pattern, name in ps.inline_patterns:
                if pattern.search(para):
                    matched_names.add(name)
                    if len(matched_names) >= PARA_DROP_THRESHOLD:
                        break
            if len(matched_names) >= PARA_DROP_THRESHOLD:
                dropped_any = True
                continue
            kept_paragraphs.append(para)
        if dropped_any:
            removed.append("paragraph_boilerplate_scored")
        surviving = "\n\n".join(kept_paragraphs).split("\n")

    # Pass 5b — inline substring removal (joined text for cross-line matching)
    if ps.inline_patterns:
        joined = "\n".join(surviving)
        for pattern, name in ps.inline_patterns:
            new_joined = pattern.sub("", joined)
            if new_joined != joined:
                if name not in removed:
                    removed.append(name)
                joined = new_joined
        surviving = joined.split("\n")

    # Pass 6 — cadastral survey coordinates (otherwise dilute embeddings)
    cleaned = "\n".join(surviving)
    cleaned = _strip_cadastral(cleaned)
    if cleaned != "\n".join(surviving):
        removed.append("cadastral_survey_description")

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return BoilerplateResult(
        cleaned_text=cleaned,
        patterns_removed=removed,
        chars_removed=original_len - len(cleaned),
    )


def strip_garbage_lines(text: str) -> str:
    """Remove heuristic-detected garbage lines (OCR noise, web artifacts)."""
    if "\xa0" in text:
        text = text.replace("\xa0", " ")
    lines = text.split("\n")
    surviving = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            surviving.append(line)
            continue
        if _classify_garbage(stripped) is None:
            surviving.append(line)
    cleaned = "\n".join(surviving)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


async def strip_boilerplate(text: str, category: str) -> BoilerplateResult:
    """Run category-specific boilerplate removal off the event loop."""
    return await asyncio.to_thread(_strip, text, category)
