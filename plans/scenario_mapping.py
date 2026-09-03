"""
B6: plan-to-scenario mapping. "Shows which clauses each scenario actually
exercises, and which clauses have never been tested at all."

Real mapping needs the Scenario library (C1-C12, not built) plus real
understanding of which plan clauses a given scenario actually exercises --
another AI/LLM-shaped problem, same family as B2/B4/B5/B9.

What's here is a pragmatic first pass using what already exists: each
plan section (from structured_extraction.py's heading split) is checked
for keyword overlap against the scenario names of real exercises that
have been run (D1, in exercises/models.py) in the same channel. A section
counts as "tested" if some exercise's scenario name shares a meaningful
word with it -- rough, but grounded in actual drills that really ran,
not a guess.
"""

import re

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is",
    "are", "this", "that", "plan", "test", "drill",
}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def map_plan_coverage(plan) -> dict:
    """
    plan: a plans.models.Plan document.
    Returns {"tested_sections": [...], "untested_sections": [...]}.
    """
    from exercises.models import Exercise

    sections = (plan.structured_data or {}).get("sections") or {}
    if not sections:
        return {"tested_sections": [], "untested_sections": []}

    exercises = Exercise.objects(slack_team_id=plan.slack_team_id) if plan.slack_team_id else Exercise.objects()
    scenario_keywords = set()
    for exercise in exercises:
        scenario_keywords |= _keywords(exercise.scenario_name)

    tested, untested = [], []
    for heading, body in sections.items():
        section_keywords = _keywords(heading) | _keywords(body[:500])
        if section_keywords & scenario_keywords:
            tested.append(heading)
        else:
            untested.append(heading)

    return {"tested_sections": tested, "untested_sections": untested}
