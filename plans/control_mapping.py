"""
B9: control mapping. "Links plan clauses to ISO 22301, ISO/IEC 27001,
NIST CSF, DORA, NIS2, PCI DSS 12.10 and applicable local regulator
requirements."

Real control mapping means matching specific plan *clauses* to specific
*sub-requirements* of each framework -- that needs real understanding of
both the plan and the frameworks (an AI/LLM dependency again, same as
B2/B4). What's here is a first pass: keyword-spotting which frameworks a
plan mentions at all, so a reviewer knows which compliance angles the
plan already touches on versus which are entirely absent.
"""

import re

# Each framework's recognizable name variants, so "ISO22301" and
# "ISO 22301" and "ISO/22301" are all treated as one hit.
FRAMEWORK_PATTERNS = {
    "ISO 22301": r"ISO[\s/-]*22301",
    "ISO/IEC 27001": r"ISO[\s/-]*(?:IEC[\s/-]*)?27001",
    "NIST CSF": r"NIST(?:\s+CSF)?",
    "DORA": r"\bDORA\b",
    "NIS2": r"\bNIS[\s-]?2\b",
    "PCI DSS": r"PCI[\s-]*DSS(?:\s*12\.10)?",
}

_COMPILED = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in FRAMEWORK_PATTERNS.items()}


def map_controls(text: str) -> dict:
    """
    Returns {"mentioned": [...], "not_mentioned": [...]} -- which of the
    known frameworks the plan's text actually references by name, versus
    which are absent. This is keyword-spotting, not real clause-level
    mapping -- a framework being "mentioned" doesn't mean the plan
    actually satisfies it.
    """
    text = text or ""
    mentioned = [name for name, pattern in _COMPILED.items() if pattern.search(text)]
    not_mentioned = [name for name in FRAMEWORK_PATTERNS if name not in mentioned]
    return {"mentioned": mentioned, "not_mentioned": not_mentioned}
