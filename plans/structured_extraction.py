"""
B2, step two: pull structured fields out of the extracted text --
RTO/RPO targets, contact details, and document sections (by heading).

This is pattern-matching, not real NLP -- it catches the common ways
these things are written ("RTO: 4 hours", "RPO 30 minutes") but won't
understand phrasing outside those patterns. Roles/triggers/escalation
paths as fully structured data are still open (would need an LLM or a
much bigger rules engine); sections at least group the raw text so a
human -- or a future LLM pass -- can find "Escalation" or "Contacts"
content quickly.
"""

import re

_TIME_UNIT = r"(?:hours?|hrs?|minutes?|mins?|days?)"

RTO_PATTERN = re.compile(
    rf"\bRTO\b\D{{0,10}}?(\d+(?:\.\d+)?\s*{_TIME_UNIT})", re.IGNORECASE
)
RPO_PATTERN = re.compile(
    rf"\bRPO\b\D{{0,10}}?(\d+(?:\.\d+)?\s*{_TIME_UNIT})", re.IGNORECASE
)
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"(?<!\d)(\+?\d[\d\-\s()]{7,}\d)(?!\d)")

HEADING_PATTERN = re.compile(r"^##\s*(.+)$", re.MULTILINE)


def extract_structured_fields(text: str) -> dict:
    if not text:
        return {"rto": [], "rpo": [], "emails": [], "phones": [], "sections": {}}

    return {
        "rto": sorted(set(m.strip() for m in RTO_PATTERN.findall(text))),
        "rpo": sorted(set(m.strip() for m in RPO_PATTERN.findall(text))),
        "emails": sorted(set(EMAIL_PATTERN.findall(text))),
        "phones": sorted(set(p.strip() for p in PHONE_PATTERN.findall(text))),
        "sections": _extract_sections(text),
    }


def _extract_sections(text: str) -> dict:
    """
    Splits text into {heading: body} using the "## Heading" markers left by
    the DOCX extractor. Only DOCX carries real heading styles today, so
    PDF/XLSX text comes back with no sections (empty dict) -- not a bug,
    just nothing to split on yet.
    """
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        return {}

    sections = {}
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections[heading] = body

    return sections
