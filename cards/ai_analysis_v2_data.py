"""
New wizard step between BIA Upload and Threat Profile: "AI Analysis" --
shows the real services/RTO/impact the AI pulled out of the uploaded
BIA/BCP (plans/resilience_map.py's output, already stored on Plan at
upload time via the real, unmodified pipeline), with Approve / Make
changes buttons before it's used to rank the Threat Profile.

Brand new screen (sir's call) -- reads Plan.resilience_map, doesn't
touch the old resilience_map_v2.py review screen at all.
"""

# Slack caps a message at 50 blocks total; each service takes 1 block,
# with ~8 more used by the header/intro/impacts/buttons around them --
# this is a real safety ceiling for an org with an unusually long
# service list, not an arbitrary display choice (so it should never
# trigger for a normal BIA/BCP).
MAX_SERVICES_SHOWN = 40

# Fixed taxonomy, not pulled per-service from the document -- matches the
# flowchart's RTO -> IMPACTS box. The uploaded doc states RTO/RPO per
# service, but doesn't tag which of these categories a disruption to a
# given service hits, so this is shown once as a reference, not repeated
# per row.
IMPACT_CATEGORIES = ["Legal", "Reputational", "Compliance", "Customer", "Operational", "Financial"]


def _rpo_from_source(svc: dict) -> str:
    """
    The AI only fills the dedicated "rpo" field some of the time -- when
    the source document's RPO column isn't explicitly labeled, the model
    still quotes the full row into "source" (e.g. "Collection | 3 days |
    2 days") without copying that trailing value into "rpo" itself. This
    recovers it from the already-returned source text instead of
    guessing -- falls back to "not stated" if "source" doesn't have a
    third segment either.
    """
    rpo = (svc.get("rpo") or "").strip()
    if rpo:
        return rpo
    source = svc.get("source") or ""
    parts = [p.strip() for p in source.split("|")]
    # parts[0] is the name, parts[1] is usually RTO (same as svc["rto"]) --
    # the RPO is whatever comes after that, if there's a third segment.
    if len(parts) >= 3:
        return parts[2]
    return ""


def _latest_plan(team_id: str):
    from plans.models import Plan

    return Plan.objects(slack_team_id=team_id, is_latest=True).order_by("-created_at").first()


def build_ai_analysis_card(team_id: str) -> dict:
    from plans.models import STATUS_PARSED

    plan = _latest_plan(team_id) if team_id else None

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":robot_face: Step · AI Analysis", "emoji": True}},
    ]

    if plan is None or plan.status != STATUS_PARSED:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "No parsed plan to analyze yet — go back and upload a BIA/BCP first."},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "← Back to Upload", "emoji": True},
                        "action_id": "v2_ai_changes",
                    }
                ],
            }
        )
        return {"blocks": blocks}

    services = (plan.resilience_map or {}).get("services") or []
    approved = plan.resilience_map_status == "approved"

    if not services:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "The AI didn't find any named services/processes with recovery objectives in this document."},
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"Found *{len(services)}* service(s) with recovery data:"},
            }
        )
        blocks.append({"type": "divider"})
        for svc in services[:MAX_SERVICES_SHOWN]:
            name = svc.get("name") or "Unnamed service"
            rto = svc.get("rto") or "not stated"
            rpo = _rpo_from_source(svc) or "not stated"
            impact = svc.get("impact_if_disrupted") or ""
            text = f"*{name}*\nRTO: `{rto}`  ·  RPO: `{rpo}`"
            if impact:
                text += f"\n_{impact}_"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        if len(services) > MAX_SERVICES_SHOWN:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"+ {len(services) - MAX_SERVICES_SHOWN} more, used in ranking but not shown here"}],
                }
            )

        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*IMPACTS* — what a disruption to any of the above can hit:\n" + " · ".join(IMPACT_CATEGORIES),
                },
            }
        )

    blocks.append({"type": "divider"})

    if approved:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Approved* — this data is being used to rank your Threat Profile."}],
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "→ Continue to Threat Profile", "emoji": True},
                        "action_id": "v2_ai_approve",
                        "style": "primary",
                    }
                ],
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Does this look right?"},
            }
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Make changes", "emoji": True},
                        "action_id": "v2_ai_changes",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                        "action_id": "v2_ai_approve",
                        "style": "primary",
                    },
                ],
            }
        )

    return {"blocks": blocks}
