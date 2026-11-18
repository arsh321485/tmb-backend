"""
Scenario review -- shown after an AI scenario is written (both the old
per-cause path from Threat Mapping/Organizational threats, and the newer
incident-wide "Build scenario" path from TestMyPlan's Configure Test).
"""


# Which label goes with which position, by how many segments the
# breadcrumb actually has -- some callers pass all 5 (module, severity,
# threat, incident, cause), others only pass the last 3 (threat,
# incident, cause) when module/severity aren't known at that point.
# Confirmed live: without a label, nobody could tell at a glance which
# word in "Cybersecurity › Critical › X › Y › Z" was the incident vs.
# the cause -- labeling by position (not by guessing from the text)
# keeps this right regardless of which specific threat/incident names
# are involved.
_BREADCRUMB_LABELS_BY_LENGTH = {
    5: ["Module", "Severity", "Threat", "Incident", "Cause"],
    4: ["Threat", "Incident", "Cause", "Scenario"],
    3: ["Threat", "Incident", "Cause"],
    2: ["Threat", "Incident"],
    1: ["Threat"],
}


def _bold_breadcrumb(breadcrumb: str) -> str:
    """Bolds each segment of a "A  ›  B  ›  C" breadcrumb AND prefixes
    each with its own label (Module/Severity/Threat/Incident/Cause),
    so the hierarchy is clear without anyone needing to remember which
    position means what."""
    parts = [p.strip() for p in breadcrumb.split("›") if p.strip()]
    labels = _BREADCRUMB_LABELS_BY_LENGTH.get(len(parts), [])
    return "  ›  ".join(
        f"_{labels[i]}:_ *{p}*" if i < len(labels) else f"*{p}*" for i, p in enumerate(parts)
    )


def _team_label_for_role(role: str) -> str:
    """Which real team (T01, T02...) a role name belongs to, from the
    same catalog Teams & Roles itself is built from -- so a reviewer can
    see at a glance which team's member gets each question, same idea
    as Threat Profile's "Continue to Configure Test" labels."""
    from .team_catalog_v2 import ALL_TEAMS, ROLE_CATALOG_BY_TEAM

    for team_id, team_roles in ROLE_CATALOG_BY_TEAM.items():
        if any(r.get("role") == role for r in team_roles):
            team = next((t for t in ALL_TEAMS if t["id"] == team_id), None)
            if team:
                return f"{team_id} ({team['name']})"
            return team_id
    return ""


_CONSEQUENCES_TAB = "__consequences__"


def build_scenario_review_card(scenario_doc, breadcrumb: str, active_phase: str = "", consequences_page: int = 0) -> dict:
    """A23 -- the exercise lead reviews the AI's actual output before
    anything here can reach a real participant. No per-field editing yet
    (sir's call: see this working end to end first) -- Approve or discard
    and regenerate are the two real actions today.

    One tab per phase that actually has an inject (Identification,
    Containment, ...), plus a trailing Consequences tab -- reviewing a
    longer, full-lifecycle scenario one phase at a time instead of one
    long scroll. This is a review-time display split only; the real
    live drill (cards/ai_drill_v2.py) still fires injects one at a time
    in strict seq order regardless of phase, unaffected by this."""
    status = scenario_doc.status

    phases_present = [p for p in scenario_doc.phases if any(i.get("phase") == p for i in scenario_doc.injects)]
    if active_phase not in phases_present and active_phase != _CONSEQUENCES_TAB:
        active_phase = phases_present[0] if phases_present else ""

    doc_id = str(scenario_doc.id)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":mag: Review Scenario — Phases, Injects & Decisions", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _bold_breadcrumb(breadcrumb)}},
    ]

    # Same real-service lookup shown under this breadcrumb everywhere
    # else it appears (Threat Mapping, Step 6 · Configure test) -- kept
    # consistent here too instead of this one screen being the odd one
    # out without it.
    if getattr(scenario_doc, "team_id", None) and getattr(scenario_doc, "threat_label", None):
        from plans.threat_ranking import mapped_services_for_threat

        mapped = mapped_services_for_threat(
            scenario_doc.team_id, {"label": scenario_doc.threat_label, "why": "", "module": scenario_doc.module},
        )
        if mapped:
            names = ", ".join(f"{s.get('name', '?')} (RTO {s.get('rto', 'unknown')})" for s in mapped)
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f":floppy_disk: *Service(s) affected:* {names}"}]})
    if status == "approved":
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ":white_check_mark: *Approved*"}]})
    blocks.append({"type": "divider"})

    if phases_present or scenario_doc.consequence_injects:
        tab_elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": p, "emoji": True},
                "action_id": f"v2_scenario_phase_tab__{idx}",
                "value": f"{doc_id}|{p}",
                **({"style": "primary"} if p == active_phase else {}),
            }
            for idx, p in enumerate(phases_present)
        ]
        if scenario_doc.consequence_injects:
            tab_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Consequences", "emoji": True},
                    "action_id": "v2_scenario_phase_tab__consequences",
                    "value": f"{doc_id}|{_CONSEQUENCES_TAB}|0",
                    **({"style": "primary"} if active_phase == _CONSEQUENCES_TAB else {}),
                }
            )
        blocks.append({"type": "actions", "elements": tab_elements})
        blocks.append({"type": "divider"})

    if active_phase == _CONSEQUENCES_TAB:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*Consequence injects (triggered by a Poor choice)*"}]})
        # Confirmed live: one section+divider PER consequence inject blew
        # past Slack's 50-block-per-message limit once an incident-wide
        # scenario combines several causes' consequences together (e.g.
        # 22 items -> 52 blocks) -- chat.update then fails silently and
        # this tab just never visibly switches. A FIXED group size (e.g.
        # "4 per block") just moves that same cliff to a bigger number
        # (confirmed: 100 items still broke it at a fixed size of 4) --
        # pack by real character count instead (this is what actually
        # protects against a huge combined list), THEN page through the
        # result a screenful at a time if there's still more than fits
        # on one message -- same "click to see the rest" pattern as the
        # Phase tabs, instead of a dead-end "+N more" note nobody could
        # act on.
        lines = []
        for inj in scenario_doc.consequence_injects:
            role = inj.get("target_role", "?")
            team_label = _team_label_for_role(role)
            to_text = f"To: {role}" + (f"  ·  _{team_label}_" if team_label else "")
            lines.append(f"*{inj.get('title', 'Untitled')}* — {to_text}\n{inj.get('inject_message', '')}")

        _CHAR_BUDGET = 2500
        packed: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            if current and current_len + len(line) + 2 > _CHAR_BUDGET:
                packed.append("\n\n".join(current))
                current, current_len = [], 0
            current.append(line)
            current_len += len(line) + 2
        if current:
            packed.append("\n\n".join(current))

        # Leave room on THIS page for a "Show more" button + its own
        # divider when there's a next page, on top of the header/
        # breadcrumb/tabs/divider already in blocks[].
        other_blocks_used = len(blocks) + 1  # final divider after this section
        page_size = max(1, 44 - other_blocks_used - 2)  # -2 reserves the "Show more" row
        start = consequences_page * page_size
        page_items = packed[start:start + page_size]
        has_more = start + page_size < len(packed)

        for text in page_items:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        if has_more:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Show more ▾", "emoji": True},
                            "action_id": "v2_scenario_consequences_page",
                            "value": f"{doc_id}|{consequences_page + 1}",
                        }
                    ],
                }
            )
        blocks.append({"type": "divider"})
    else:
        for inj in scenario_doc.injects:
            if inj.get("phase") != active_phase:
                continue
            role = inj.get("target_role", "?")
            team_label = _team_label_for_role(role)
            lines = [f"*{inj.get('seq', '?')}. {inj.get('title', 'Untitled')}* — _{inj.get('phase', '')}_"]
            lines.append(f"To: *{role}*" + (f"  ·  _{team_label}_" if team_label else ""))
            lines.append(inj.get("inject_message", ""))
            lines.append(f"\n*Decision:* {inj.get('decision_question', '')}")
            for opt in inj.get("options", []):
                lines.append(f"  • ({opt.get('rating', '?')}, {opt.get('score', '?')}/10) {opt.get('option_text', '')}")
            block = {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}
            blocks.append(block)
            blocks.append({"type": "divider"})

    if status == "approved":
        # There's no separate "Trigger" nav tab any more (sir's call), so
        # coming back to an already-approved scenario needs its own way
        # back to that screen -- this button, not a dead end.
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Continue to Trigger", "emoji": True},
                        "action_id": "v2_scenario_goto_trigger",
                        "value": doc_id,
                        "style": "primary",
                    }
                ],
            }
        )
    else:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve this scenario", "emoji": True},
                        "action_id": "v2_scenario_approve",
                        "value": str(scenario_doc.id),
                        "style": "primary",
                    },
                ],
            }
        )
    return {"blocks": blocks}
