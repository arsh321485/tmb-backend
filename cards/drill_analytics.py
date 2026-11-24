"""
Real computations for the Drill Analytics screens, built entirely from
data already captured during a live run (AIDecisionResponse's real
sent_at/due_at/responded_at/target_role/is_backup fields) -- nothing
here is a placeholder or invented number.

"Planned" time per decision is its own due_at (the real response-timer
deadline set when that inject was sent, cards/ai_drill_v2.py's
_send_inject_dm) minus sent_at. "Actual" is responded_at minus sent_at.
Summed across every decision, that's genuinely "planned vs. actual
total response time" -- not a guess.

Deliberately NOT built here (would need data this app doesn't capture
yet): RTO/RPO-achieved-vs-planned during a drill, and the privacy-
breach notification-clock milestones -- both need a different drill
mechanic (named recovery/notification milestones, not generic Q&A
injects) that doesn't exist yet. See the team's conversation for that
scoping; this module only covers what's real today.
"""

import datetime
import statistics

from .models_v2 import AIDecisionResponse
from .team_catalog_v2 import ALL_TEAMS, ROLE_CATALOG_BY_TEAM

_PREP_BUCKETS = [
    (0, 50, "At risk", (190, 40, 50)),
    (50, 75, "Developing", (184, 120, 40)),
    (75, 90, "Prepared", (74, 199, 183)),
    (90, 101, "Resilient", (26, 140, 90)),
]


def _bucket_for(score: int) -> tuple:
    for lo, hi, label, color in _PREP_BUCKETS:
        if lo <= score < hi:
            return label, color
    return "Resilient", _PREP_BUCKETS[-1][3]


def _team_for_role(role: str) -> dict | None:
    for team_id, roles in ROLE_CATALOG_BY_TEAM.items():
        if any(r.get("role") == role for r in roles):
            return next((t for t in ALL_TEAMS if t["id"] == team_id), None)
    return None


def _minutes(delta: datetime.timedelta) -> float:
    return delta.total_seconds() / 60


def _inject_phase_map(scenario) -> dict:
    return {inj.get("inject_id", ""): inj.get("phase", "") for inj in scenario.injects}


def compute_overview(run) -> dict:
    scenario = run.scenario
    responses = list(AIDecisionResponse.objects(run=run))
    phase_of = _inject_phase_map(scenario)

    answered = [r for r in responses if r.responded_at]
    planned_total = sum(_minutes(r.due_at - r.sent_at) for r in answered if r.due_at)
    actual_total = sum(_minutes(r.responded_at - r.sent_at) for r in answered)

    preparedness = round(100 * planned_total / actual_total) if actual_total > 0 else 0
    preparedness = max(0, min(100, preparedness))
    bucket_label, bucket_color = _bucket_for(preparedness)

    on_time = sum(1 for r in answered if r.due_at and r.responded_at <= r.due_at)
    total_actions = len(responses)

    notified = set(r.assigned_slack_user_id for r in responses)
    responded_people = set(r.assigned_slack_user_id for r in answered)
    participation_pct = round(100 * len(responded_people) / len(notified)) if notified else 0

    ack_seconds = [(r.responded_at - r.sent_at).total_seconds() for r in answered]
    median_ack = statistics.median(ack_seconds) if ack_seconds else 0

    backups_activated = len(set(r.assigned_slack_user_id for r in responses if r.is_backup))

    phase_rows = []
    phases_seen = []
    for r in answered:
        phase = phase_of.get(r.inject_id, "")
        if phase and phase not in phases_seen:
            phases_seen.append(phase)
    for phase in phases_seen:
        phase_responses = [r for r in answered if phase_of.get(r.inject_id) == phase]
        p_planned = sum(_minutes(r.due_at - r.sent_at) for r in phase_responses if r.due_at)
        p_actual = sum(_minutes(r.responded_at - r.sent_at) for r in phase_responses)
        phase_rows.append({"phase": phase, "planned_min": p_planned, "actual_min": p_actual})

    return {
        "breadcrumb": f"{scenario.threat_label}  ›  {scenario.incident_name}",
        "module": scenario.module,
        "title": scenario.cause_name or scenario.incident_name,
        "started_at": run.started_at if getattr(run, "started_at", None) else None,
        "team_count": len({t["id"] for t in (_team_for_role(r.target_role) for r in responses) if t}),
        "people_count": len(notified),
        "actions_total": total_actions,
        "preparedness": preparedness,
        "bucket_label": bucket_label,
        "bucket_color": bucket_color,
        "planned_total_min": planned_total,
        "actual_total_min": actual_total,
        "actions_on_time": on_time,
        "participation_pct": participation_pct,
        "responded_count": len(responded_people),
        "notified_count": len(notified),
        "median_ack_seconds": median_ack,
        "backups_activated": backups_activated,
        "phases": phase_rows,
    }


def compute_team_breakdown(run) -> dict:
    scenario = run.scenario
    responses = list(AIDecisionResponse.objects(run=run))
    answered = [r for r in responses if r.responded_at]

    by_team: dict = {}
    for r in responses:
        team = _team_for_role(r.target_role)
        if not team:
            continue
        row = by_team.setdefault(team["id"], {"name": team["name"], "actions_total": 0, "actions_done": 0, "planned_min": 0.0, "actual_min": 0.0, "responses": []})
        row["actions_total"] += 1
        row["responses"].append(r)
        if r.responded_at:
            row["actions_done"] += 1
            if r.due_at:
                row["planned_min"] += _minutes(r.due_at - r.sent_at)
            row["actual_min"] += _minutes(r.responded_at - r.sent_at)

    rows = []
    for team_id, data in by_team.items():
        deviation = data["actual_min"] - data["planned_min"]
        pct = round(100 * deviation / data["planned_min"]) if data["planned_min"] > 0 else 0
        rows.append({
            "team_id": team_id, "name": data["name"],
            "actions_done": data["actions_done"], "actions_total": data["actions_total"],
            "planned_min": data["planned_min"], "actual_min": data["actual_min"],
            "deviation_min": deviation, "deviation_pct": pct,
        })
    rows.sort(key=lambda r: r["deviation_min"], reverse=True)

    total_planned = sum(r["planned_min"] for r in rows)
    total_actual = sum(r["actual_min"] for r in rows)
    total_done = sum(r["actions_done"] for r in rows)
    total_actions = sum(r["actions_total"] for r in rows)

    # Bottleneck: the single slowest real answered decision -- a real
    # data point (that specific role took the longest to respond),
    # not an invented narrative about why.
    bottleneck = None
    slowest = max(answered, key=lambda r: (r.responded_at - r.sent_at), default=None)
    if slowest:
        inject = None
        for inj in scenario.injects:
            if inj.get("inject_id") == slowest.inject_id:
                inject = inj
                break
        wait_min = _minutes(slowest.responded_at - slowest.sent_at)
        team = _team_for_role(slowest.target_role)
        bottleneck = {
            "team_name": team["name"] if team else slowest.target_role,
            "wait_min": wait_min,
            "title": inject.get("title", "") if inject else "",
        }

    # Single point of failure: a team where only one real person
    # answered every one of its decisions (no backup ever stepped in) --
    # also a real, observable fact from who actually answered.
    spof = None
    for team_id, data in by_team.items():
        people = {r.assigned_slack_user_id for r in data["responses"]}
        has_backup = any(r.is_backup for r in data["responses"])
        if len(people) == 1 and not has_backup and data["actions_done"] > 0:
            spof = {"team_name": data["name"]}
            break

    return {
        "breadcrumb": f"{scenario.threat_label}  ›  {scenario.incident_name}",
        "rows": rows,
        "total_planned_min": total_planned,
        "total_actual_min": total_actual,
        "total_done": total_done,
        "total_actions": total_actions,
        "bottleneck": bottleneck,
        "spof": spof,
    }
