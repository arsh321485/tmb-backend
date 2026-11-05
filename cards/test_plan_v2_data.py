"""Step 6 · Test plan -- the phased checklist for the chosen scenario."""

import json

PHASES = {
    "Cybersecurity": [
        {"name": "Threat confirmed & triage", "steps": ["Validate the first alert against the threat", "Confirm the incident type and severity", "Open the war room and assign roles"]},
        {"name": "Containment", "steps": ["Make the containment decision on the bridge", "Execute and confirm the action", "Preserve forensic evidence before cleanup"]},
        {"name": "Cause & spread", "steps": ["Trace the cause back to patient zero", "Check who else the cause reached", "Close the entry point"]},
        {"name": "Notification", "steps": ["Brief legal, privacy and leadership", "Prepare external holding lines"]},
        {"name": "Recovery & review", "steps": ["Restore affected systems and validate", "Measure detection and containment times", "Log evidence for the hot-wash"]},
    ],
    "default": [
        {"name": "Trigger & triage", "steps": ["Validate the first alert", "Declare severity and open the bridge", "Assign roles from the response team"]},
        {"name": "Containment", "steps": ["Make the containment decision", "Execute and confirm the action"]},
        {"name": "Notification", "steps": ["Brief legal and leadership", "Prepare external holding lines"]},
        {"name": "Recovery & review", "steps": ["Restore and validate", "Log evidence for the hot-wash"]},
    ],
}


def _resolve_step_assignment(step: dict, slack_team_id: str, bot_token: str) -> str:
    """
    The spreadsheet's "teams"/"roles" columns are just text (e.g. "SOC
    Analyst - Tier 1 (Triage)") -- sir's call: show who that actually is
    right now, the real team name plus the real primary/backup assigned
    to that role on the Teams card, not just the role label.
    """
    from . import persistence_v2
    from .team_catalog_v2 import find_team_by_name

    team = find_team_by_name(step.get("teams", ""))
    if not team:
        return ""

    roles = [r.strip() for r in step.get("roles", "").split("|") if r.strip()]
    members = persistence_v2.load_teams_state(slack_team_id)["teams"].get(team["id"], [])

    by_code = {}
    if bot_token:
        from .slack_members_v2 import get_workspace_people

        by_code = {p["i"]: p for p in get_workspace_people(bot_token)}

    lines = [f"*Team*\n{team['name']}"]
    for role in roles:
        member = next((m for m in members if m["role"] == role), None)
        primary_id = member["primary"][0] if member and member.get("primary") else None
        backup_id = member["backup"][0] if member and member.get("backup") else None
        primary_text = by_code.get(primary_id, {}).get("n") if primary_id else None
        backup_text = by_code.get(backup_id, {}).get("n") if backup_id else None
        lines.append(
            f"*{role}*\nPrimary: {primary_text or '_Not yet assigned_'}  ·  Backup: {backup_text or '_Not yet assigned_'}"
        )
    return "\n\n".join(lines)


def build_configure_test_card(
    module: str, threat_key: str, incident_id: str, active_cause: str,
    active_phase: str, active_scenario: str, breadcrumb: dict, team_id: str = "",
) -> dict:
    """
    Cause/Phase/Scenario picker for a pre-built plan -- moved here from
    the Threat Profile card (sir's call): Threat Profile now stops at
    Incident, Cause/Phase/Scenario all get chosen here before Triggering.
    Cause determines which real plan_id applies (plan_catalog_v2's
    taxonomy is keyed by module+threat+incident+cause), so it's resolved
    first, then Phase/Scenario as before. All three tab rows stay
    visible together, same as Phase+Scenario already did.
    """
    from .threat_map_v2_data import _find_threat

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":clipboard: Step 6 · Configure test", "emoji": True}},
    ]

    taxonomy_threat = _find_threat(module, threat_key) if module and threat_key else None
    incident = next((i for i in (taxonomy_threat or {}).get("incidents", []) if i["id"] == incident_id), None)
    causes = incident["causes"] if incident else []
    # Strict step-by-step disclosure (sir's call, same as Threat Profile
    # above it) -- no auto-picking "the first one"; nothing shows as
    # selected, and nothing below Cause renders, until the admin
    # actually clicks it.
    if not any(c["id"] == active_cause for c in causes):
        active_cause = ""
    selected_cause = next((c for c in causes if c["id"] == active_cause), None)

    crumb = dict(breadcrumb)
    if selected_cause:
        crumb["cause"] = selected_cause["name"]
    crumb_text = "  ›  ".join(f"*{crumb[k]}*" for k in ("module", "crit", "threat", "incident", "cause") if crumb.get(k))
    if crumb_text:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":round_pushpin: {crumb_text}"}})
        blocks.append({"type": "divider"})

    def _cfg_value(**overrides) -> str:
        payload = {
            "module": module, "threat_key": threat_key, "incident_id": incident_id,
            "cause": active_cause, "phase": active_phase, "scenario": active_scenario,
            "breadcrumb": breadcrumb,
        }
        payload.update(overrides)
        return json.dumps(payload)

    if causes:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "`CAUSE`"}]})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": c["name"], "emoji": True},
                        "action_id": f"v2_cfgtest_cause_tab__{c['id']}",
                        "value": _cfg_value(cause=c["id"], phase="", scenario=""),
                        **({"style": "primary"} if c["id"] == active_cause else {}),
                    }
                    for c in causes
                ],
            }
        )

    if not selected_cause:
        return {"blocks": blocks}

    # Awareness content now shown as a real popup (sir's call) --
    # see cards/cause_awareness_modal_v2.py, opened by the handler for
    # v2_cfgtest_cause_tab__ right when the cause is clicked, not as
    # text stuffed into this screen.

    from .plan_catalog_v2 import find_plan_id_for_taxonomy, phases_for_plan, steps_for_phase

    plan_id = find_plan_id_for_taxonomy(module, threat_key, incident_id, active_cause)

    # A22 -- every cause except the ones with a hand-written plan lands
    # here with nothing real to run. Instead of a dead end, offer to
    # have the AI write a real scenario for this exact
    # Threat -> Incident -> Cause, from this workspace's own plan and
    # assigned roles. Moved here from Threat Profile (sir's call) since
    # this screen now owns Cause -- it's the one with the real
    # cause-specific plan_id (or lack of one) to check against.
    from .models_v2 import GeneratedScenario

    existing = None
    if team_id:
        existing = GeneratedScenario.objects(
            team_id=team_id, module=module, threat_id=threat_key,
            incident_id=incident_id, cause_id=active_cause,
        ).order_by("-created_at").first()

    if not plan_id:
        if existing:
            status_text = ":white_check_mark: *AI scenario approved* -- ready to run." if existing.status == "approved" else ":memo: *AI scenario written* -- needs review and approval."
            review_label = ":white_check_mark: Review approved AI scenario" if existing.status == "approved" else ":mag: Review AI scenario"
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": status_text}]})
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": review_label, "emoji": True},
                            "action_id": "v2_threat_scenario_review",
                            "value": str(existing.id),
                            "style": "primary",
                        }
                    ],
                }
            )
        else:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_No pre-built plan for this cause yet._"}]})
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": ":sparkles: Generate real scenario with AI", "emoji": True},
                            "action_id": "v2_threat_scenario_generate",
                            "value": f"{module}|{threat_key}|{incident_id}|{active_cause}",
                        }
                    ],
                }
            )
        return {"blocks": blocks}

    phases = phases_for_plan(plan_id)
    if active_phase not in phases:
        active_phase = ""

    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "`PHASE`"}]})
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": p, "emoji": True},
                    "action_id": f"v2_cfgtest_phase_tab__{idx}",
                    "value": _cfg_value(phase=p, scenario=""),
                    **({"style": "primary"} if p == active_phase else {}),
                }
                for idx, p in enumerate(phases)
            ],
        }
    )

    if not active_phase:
        return {"blocks": blocks}

    steps = steps_for_phase(plan_id, active_phase)
    if not steps:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No scenarios in this phase._"}})
        return {"blocks": blocks}

    if active_scenario not in {s["scenario"] for s in steps}:
        active_scenario = steps[0]["scenario"]

    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "`SCENARIO`"}]})
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": s["scenario"], "emoji": True},
                    "action_id": f"v2_cfgtest_scenario_tab__{idx}",
                    "value": _cfg_value(scenario=s["scenario"]),
                    # All green, same as the old inline picker -- Trigger
                    # runs every scenario in the phase, not just the last one clicked.
                    "style": "primary",
                }
                for idx, s in enumerate(steps)
            ],
        }
    )

    blocks.append({"type": "divider"})
    trigger_row = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": ":rotating_light: Launch test", "emoji": True},
            "action_id": "v2_threat_trigger",
            "value": json.dumps({"plan_id": plan_id, "phase": active_phase, "scenario": active_scenario, **crumb}),
            "style": "danger",
        }
    ]
    # Sir's call: even a cause with a fixed pre-built plan can ALSO get
    # a fresh AI-written one from the org's real plan -- not a
    # replacement for the plan above, just an extra real option next to
    # it. Same "review before it's usable" gate as every other
    # AI-generated one.
    if existing:
        review_label = ":white_check_mark: Review approved AI scenario" if existing.status == "approved" else ":mag: Review AI scenario"
        trigger_row.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": review_label, "emoji": True},
                "action_id": "v2_threat_scenario_review",
                "value": str(existing.id),
            }
        )
    else:
        trigger_row.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": ":sparkles: Generate real scenario with AI", "emoji": True},
                "action_id": "v2_threat_scenario_generate",
                "value": f"{module}|{threat_key}|{incident_id}|{active_cause}",
            }
        )
    blocks.append({"type": "actions", "elements": trigger_row})
    return {"blocks": blocks}


def build_real_test_plan_card(
    plan_id: str, active_phase: str, active_scenario: str, breadcrumb: dict | None = None,
    slack_team_id: str = "", bot_token: str = "",
) -> dict:
    """Real plan content (sir's spreadsheet), reached via the Threat Profile
    card's new Phase/Scenario tabs + Trigger button."""
    from .plan_catalog_v2 import PLAN_META, steps_for_phase

    meta = PLAN_META.get(plan_id, {})
    current_step = next((s for s in steps_for_phase(plan_id, active_phase) if s["scenario"] == active_scenario), None)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":clipboard: Step 6 · Test plan", "emoji": True}},
    ]

    # The full selection path that got here -- Module > Criticality >
    # Threat > Incident > Cause > Phase > Scenario -- in one line, so
    # it's clear what this plan is for without scrolling back up to the
    # Threat Profile card. Only shown when the Trigger button passed it
    # through (older/legacy entry points into this card don't have it).
    if breadcrumb:
        crumb_text = "  ›  ".join(
            f"*{breadcrumb[k]}*" for k in ("module", "crit", "threat", "incident", "cause", "phase", "scenario") if breadcrumb.get(k)
        )
        if crumb_text:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":round_pushpin: {crumb_text}"}})
            blocks.append({"type": "divider"})

    blocks += [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f":red_circle: *{active_phase}* · Plan {plan_id}"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{meta.get('incident', '')}*\n_{meta.get('cause', '')}_"}},
        {"type": "divider"},
    ]

    if current_step:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":large_blue_circle: *{current_step['scenario']}*"},
            }
        )

        if slack_team_id:
            assignment_text = _resolve_step_assignment(current_step, slack_team_id, bot_token)
            if assignment_text:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": assignment_text}})

        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Task*\n{current_step['task']}"},
            }
        )

        instructions = current_step.get("instructions")
        if instructions:
            from .plan_catalog_v2 import parse_form_instructions

            if current_step.get("response_type") == "form":
                fields = parse_form_instructions(instructions)
                lines = []
                for f in fields:
                    if f.get("options"):
                        lines.append(f"• *{f['label']}* — {', '.join(f['options'])}")
                    else:
                        lines.append(f"• *{f['label']}*")
                instructions_text = "\n".join(lines)
            else:
                instructions_text = "\n".join(f"• {part.strip()}" for part in instructions.split("|") if part.strip())

            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Instructions*\n{instructions_text}"},
                }
            )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":rocket: TestMyPlan", "emoji": True},
                    "action_id": "v2_plan_arm_real",
                    "value": f"{plan_id}:{active_phase}:{active_scenario}",
                    "style": "danger",
                },
            ],
        }
    )
    return {"blocks": blocks}


def _compact_step_assignment(step: dict, team_catalog_by_name: dict, members_by_team: dict, by_code: dict, acknowledgments: dict | None = None) -> str:
    """One short line per scenario: name, team code, primary/backup only --
    sir's call: the full team/role text per row made the summary unreadable
    (wall of text), so this drops down to just what's needed to scan fast.
    A small check/hourglass per person shows whether they've actually
    acknowledged that role yet -- readiness, visible before a drill fires."""
    team = team_catalog_by_name.get(step.get("teams", ""))
    team_code = team["id"] if team else "—"
    members = members_by_team.get(team["id"], []) if team else []
    acknowledgments = acknowledgments or {}

    roles = [r.strip() for r in step.get("roles", "").split("|") if r.strip()]
    pairs = []
    for role in roles:
        member = next((m for m in members if m["role"] == role), None)
        primary_id = member["primary"][0] if member and member.get("primary") else None
        backup_id = member["backup"][0] if member and member.get("backup") else None
        acked = acknowledgments.get((team_code, role), set())

        def _tag(uid):
            if not uid:
                return "—"
            name = by_code.get(uid, {}).get("n", uid)
            return f"{name} {'✅' if uid in acked else '⏳'}"

        pairs.append(f"{_tag(primary_id)}/{_tag(backup_id)}")
    assign_text = " · ".join(pairs) if pairs else "—"

    return f"*{step['scenario']}*  `{team_code}`  {assign_text}"


def build_plan_summary_card(
    plan_id: str, slack_team_id: str = "", bot_token: str = "",
    back_phase: str = "", back_scenario: str = "", breadcrumb: dict | None = None,
) -> dict:
    """
    Table-like roster across EVERY scenario in the plan -- Scenario, Team,
    Role, Primary, Backup, plus a total count -- since the single-step
    view (build_real_test_plan_card) only ever shows the one scenario
    picked on Threat Profile. Slack has no real table element, so each
    scenario is one compact bullet line instead, grouped by phase and
    chunked to stay well under the 50-block-per-message limit.
    """
    from . import persistence_v2
    from .plan_catalog_v2 import PLAN_META, phases_for_plan, steps_for_phase
    from .team_catalog_v2 import ALL_TEAMS

    meta = PLAN_META.get(plan_id, {})
    phases = phases_for_plan(plan_id)
    total_steps = sum(len(steps_for_phase(plan_id, p)) for p in phases)

    team_catalog_by_name = {t["name"]: t for t in ALL_TEAMS}
    members_by_team = persistence_v2.load_teams_state(slack_team_id)["teams"] if slack_team_id else {}
    acknowledgments = persistence_v2.load_acknowledgments(slack_team_id) if slack_team_id else {}
    by_code = {}
    if bot_token:
        from .slack_members_v2 import get_workspace_people

        by_code = {p["i"]: p for p in get_workspace_people(bot_token)}

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":bar_chart: Test plan summary", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f":red_circle: *{total_steps} scenarios* · Plan {plan_id}"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{meta.get('incident', '')}*\n_{meta.get('cause', '')}_"}},
        {"type": "divider"},
    ]

    icons = ["one", "two", "three", "four", "five", "six"]
    for i, phase in enumerate(phases, 1):
        steps = steps_for_phase(plan_id, phase)
        lines = [_compact_step_assignment(s, team_catalog_by_name, members_by_team, by_code, acknowledgments) for s in steps]

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f":{icons[i - 1]}: *{phase}*  ·  {len(steps)} scenario{'s' if len(steps) != 1 else ''}"}})
        # Chunked to a handful of rows per block, well clear of Slack's
        # 3000-char section text limit and 50-block message limit even
        # for a plan's biggest phase.
        for chunk_start in range(0, len(lines), 8):
            chunk = lines[chunk_start:chunk_start + 8]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f"• {line}" for line in chunk)}})
        blocks.append({"type": "divider"})

    if back_phase and back_scenario:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "← Back to plan", "emoji": True},
                        "action_id": "v2_plan_summary_back",
                        "value": json.dumps({"plan_id": plan_id, "phase": back_phase, "scenario": back_scenario, "breadcrumb": breadcrumb or {}}),
                    }
                ],
            }
        )

    return {"blocks": blocks}


def build_test_plan_card(module: str, scenario: str) -> dict:
    phases = PHASES.get(module, PHASES["default"])
    total_steps = sum(len(p["steps"]) for p in phases)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":clipboard: Step 6 · Test plan", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f":red_circle: *{total_steps} steps*"}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{scenario}*"}},
        {"type": "divider"},
    ]

    for i, phase in enumerate(phases, 1):
        step_lines = "\n".join(f"• {s}" for s in phase["steps"])
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":{['one','two','three','four','five','six'][i-1]}: *{phase['name']}*\n{step_lines}"},
            }
        )
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": ":rocket: TestMyPlan", "emoji": True},
                    "action_id": "v2_plan_arm",
                    "value": f"{module}:{scenario}",
                    "style": "danger",
                }
            ],
        }
    )
    return {"blocks": blocks}
