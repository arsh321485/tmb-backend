"""
B4: plan gap review. "Flags undefined owners, missing escalation criteria,
conflicting recovery targets and absent regulator notification steps
before a single drill is run."

Built on top of structured_extraction.py's pattern-matched fields --
inherits the same limitation (it can only flag what pattern-matching
found or didn't find, not truly judge whether the plan is good). Full
gap review needs real understanding of the plan's content, which is the
same open AI/LLM dependency as B2.
"""

GAP_MISSING_RTO = "missing_rto"
GAP_MISSING_RPO = "missing_rpo"
GAP_MISSING_CONTACTS = "missing_contacts"
GAP_NO_SECTIONS = "no_sections"
GAP_CONFLICTING_RTO = "conflicting_rto"
GAP_CONFLICTING_RPO = "conflicting_rpo"

_GAP_MESSAGES = {
    GAP_MISSING_RTO: "No RTO (Recovery Time Objective) found.",
    GAP_MISSING_RPO: "No RPO (Recovery Point Objective) found.",
    GAP_MISSING_CONTACTS: "No escalation contacts (emails/phone numbers) found.",
    GAP_NO_SECTIONS: "No headed sections found -- plan may be unstructured or a scanned/image document.",
    GAP_CONFLICTING_RTO: "Multiple different RTO values found -- may be conflicting targets.",
    GAP_CONFLICTING_RPO: "Multiple different RPO values found -- may be conflicting targets.",
}


def find_gaps(structured_data: dict) -> list[dict]:
    """
    Returns a list of {"code": ..., "message": ...} gaps found in a plan's
    structured_data (see structured_extraction.py). Empty list = no gaps
    detected by these checks (not a guarantee the plan is actually complete).
    """
    structured_data = structured_data or {}
    gaps = []

    rto = structured_data.get("rto") or []
    rpo = structured_data.get("rpo") or []
    contacts = (structured_data.get("emails") or []) + (structured_data.get("phones") or [])
    sections = structured_data.get("sections") or {}

    if not rto:
        gaps.append(_gap(GAP_MISSING_RTO))
    elif len(rto) > 1:
        gaps.append(_gap(GAP_CONFLICTING_RTO, values=rto))

    if not rpo:
        gaps.append(_gap(GAP_MISSING_RPO))
    elif len(rpo) > 1:
        gaps.append(_gap(GAP_CONFLICTING_RPO, values=rpo))

    if not contacts:
        gaps.append(_gap(GAP_MISSING_CONTACTS))

    if not sections:
        gaps.append(_gap(GAP_NO_SECTIONS))

    return gaps


def _gap(code: str, **details) -> dict:
    gap = {"code": code, "message": _GAP_MESSAGES[code]}
    if details:
        gap["details"] = details
    return gap
