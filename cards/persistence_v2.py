"""
Real save/load for the new-design admin flow's Threats and Module Admins
steps (Day 1 of the real backend -- see cards/models_v2.py). Every
mutating click now writes through to the database, and every time the
step is (re)opened (nav jump, first visit), it loads the real saved
state instead of starting blank.
"""

from .models_v2 import AdminSetup, ScenarioSelection, Team, TeamMember


def _get_or_create(team_id: str) -> AdminSetup:
    setup = AdminSetup.objects(team_id=team_id).first()
    if setup is None:
        setup = AdminSetup(team_id=team_id)
        setup.save()
    return setup


def load_threats_state(team_id: str) -> dict:
    setup = AdminSetup.objects(team_id=team_id).first()
    if setup is None:
        return {"fixed": {}, "custom": [], "form": None}
    fixed = {t["threat_id"]: t["criticality"] for t in setup.confirmed_threats}
    custom = [{"module": c["module"], "label": c["label"], "crit": c["criticality"]} for c in setup.custom_threats]
    return {"fixed": fixed, "custom": custom, "form": None}


def save_threats_state(team_id: str, state: dict) -> None:
    setup = _get_or_create(team_id)
    fixed = state.get("fixed", {})
    custom = state.get("custom", [])
    setup.confirmed_threats = [{"threat_id": key, "criticality": crit} for key, crit in fixed.items()]
    setup.custom_threats = [
        {"module": c["module"], "label": c["label"], "criticality": c["crit"]} for c in custom
    ]
    setup.save()


NAV_FIELDS = ("active_module", "active_crit", "active_threat", "active_incident", "active_cause", "active_phase", "active_scenario")


def load_threat_profile_nav(team_id: str) -> dict:
    setup = AdminSetup.objects(team_id=team_id).first()
    nav = (setup.threat_profile_nav if setup else {}) or {}
    return {field: nav.get(field) for field in NAV_FIELDS}


def save_threat_profile_nav(team_id: str, nav: dict) -> None:
    setup = _get_or_create(team_id)
    setup.threat_profile_nav = {field: nav.get(field) for field in NAV_FIELDS}
    setup.save()


def load_visited_combos(team_id: str) -> set:
    setup = AdminSetup.objects(team_id=team_id).first()
    return set(setup.threat_profile_visited_combos) if setup else set()


def save_visited_combos(team_id: str, combos: set) -> None:
    setup = _get_or_create(team_id)
    setup.threat_profile_visited_combos = list(combos)
    setup.save()


def load_admins_state(team_id: str) -> dict:
    setup = AdminSetup.objects(team_id=team_id).first()
    assigned = dict(setup.module_admins) if setup else {}
    return {"assigned": assigned, "expanded": None, "delegate_pick": None}


def save_admins_state(team_id: str, assigned: dict) -> None:
    setup = _get_or_create(team_id)
    setup.module_admins = dict(assigned)
    setup.save()


def get_module_owner(team_id: str, module_id: str) -> str:
    """The real Slack user id assigned to a module (e.g. "plans_bia"),
    or "" if nobody's been assigned yet. Used to restrict Phase 1's
    plan upload/confirm/lock to only the assigned Plans & BIA owner."""
    setup = AdminSetup.objects(team_id=team_id).first()
    if not setup:
        return ""
    owner = (setup.module_admins or {}).get(module_id, "")
    # "invited:Name|email" means someone was invited by email but isn't
    # a real Slack member yet -- not a usable Slack user id.
    return "" if owner.startswith("invited:") else owner


def load_scenario_selection(team_id: str, module: str) -> dict:
    sel = ScenarioSelection.objects(team_id=team_id, module=module).first()
    if sel is None:
        return {"threat_id": "", "incident_id": "", "cause_id": "", "scenario_id": "", "phase": "", "armed": False, "armed_at": None}
    return {
        "threat_id": sel.threat_id or "",
        "incident_id": sel.incident_id or "",
        "cause_id": sel.cause_id or "",
        "scenario_id": sel.scenario_id or "",
        "phase": getattr(sel, "phase", "") or "",
        "armed": sel.armed,
        "armed_at": sel.armed_at,
    }


def save_scenario_selection(team_id: str, module: str, **fields) -> None:
    sel = ScenarioSelection.objects(team_id=team_id, module=module).first()
    if sel is None:
        sel = ScenarioSelection(team_id=team_id, module=module)
    for key, value in fields.items():
        setattr(sel, key, value)
    sel.save()


def _team_module_and_name(team_key: str) -> tuple:
    from .team_catalog_v2 import find_team

    t = find_team(team_key)
    if t:
        return t["tier"], t["name"], t["tier"] == "Mandatory"
    return "Custom", team_key, False


def load_acknowledgments(team_id: str) -> dict:
    """
    {(catalog_team_id, role): {slack_user_id, ...}} -- who has actually
    acknowledged each role (Welcome -> Role -> Acknowledge flow), for the
    Test Plan summary to show readiness without needing a drill to have
    fired first. Kept separate from load_teams_state so every other
    caller of that function is unaffected.
    """
    from .team_catalog_v2 import ALL_TEAMS

    by_role = {}
    for team_doc in Team.objects(team_id=team_id):
        slug = team_doc.slug
        if not any(t["id"] == slug for t in ALL_TEAMS):
            continue
        for tm in TeamMember.objects(team=team_doc):
            by_role[(slug, tm.role)] = set((tm.acknowledged_by or {}).keys())
    return by_role


def record_dm_status(slack_team_id: str, catalog_team_id: str, role: str, slack_user_id: str, status: str) -> None:
    """
    Records whether the real Welcome DM (role_welcome_v2.send_welcome_dm)
    actually reached this person -- "sent" or "failed", from the real
    Slack API call's own result -- so Configure Teams can show real
    delivery status, not just "assigned".
    """
    team_doc = Team.objects(team_id=slack_team_id, slug=catalog_team_id).first()
    if not team_doc:
        return
    tm = TeamMember.objects(team=team_doc, role=role).first()
    if not tm:
        return
    tm.dm_status[slack_user_id] = status
    if status == "sent":
        import datetime

        tm.dm_sent_at[slack_user_id] = datetime.datetime.utcnow()
    tm.save()


def save_teams_card_location(team_id: str, channel_id: str, message_ts: str) -> None:
    if not (channel_id and message_ts):
        return
    setup = _get_or_create(team_id)
    setup.teams_card_location = {"channel_id": channel_id, "message_ts": message_ts}
    setup.save()


def load_teams_card_location(team_id: str) -> dict:
    setup = AdminSetup.objects(team_id=team_id).first()
    return dict(setup.teams_card_location) if setup and setup.teams_card_location else {}


def load_dm_statuses(team_id: str) -> dict:
    """{(catalog_team_id, role): {slack_user_id: "sent"|"failed", ...}} --
    same shape/pattern as load_acknowledgments, for Configure Teams to show
    delivery status per person."""
    from .team_catalog_v2 import ALL_TEAMS

    by_role = {}
    for team_doc in Team.objects(team_id=team_id):
        slug = team_doc.slug
        if not any(t["id"] == slug for t in ALL_TEAMS):
            continue
        for tm in TeamMember.objects(team=team_doc):
            by_role[(slug, tm.role)] = dict(tm.dm_status or {})
    return by_role


def load_teams_state(team_id: str) -> dict:
    """
    Mirrors teams_v2_data.read_current_state()'s shape, but sourced from
    the database instead of parsing the Slack message.
    """
    from .team_catalog_v2 import ALL_TEAMS

    teams = {t["id"]: [] for t in ALL_TEAMS}
    resp = {t["id"]: [] for t in ALL_TEAMS}

    for team_doc in Team.objects(team_id=team_id):
        for tm in TeamMember.objects(team=team_doc):
            teams.setdefault(team_doc.slug, []).append(
                {"role": tm.role, "primary": list(tm.primary_slack_user_ids), "backup": list(tm.backup_slack_user_ids)}
            )
            for mr in tm.mapped_responsibilities:
                resp.setdefault(team_doc.slug, []).append(
                    {
                        "text": mr.get("responsibility", ""),
                        "who": tm.role,
                        "action": mr.get("action", ""),
                        "detail": mr.get("detail", ""),
                        "phase": mr.get("phase", ""),
                    }
                )

    return {"teams": teams, "resp": resp, "add": None, "map": None, "dm_open": set(), "active_tier": "Mandatory", "expanded_team": None}


def save_teams_state(team_id: str, teams: dict, resp: dict) -> None:
    """
    Saves every team/role currently in `teams` (as built by
    teams_v2_data.read_current_state()) to the database, along with
    whatever responsibilities are mapped to each role in `resp`.
    """
    for team_key, members in (teams or {}).items():
        module, name, is_mandatory = _team_module_and_name(team_key)
        team_doc = Team.objects(team_id=team_id, slug=team_key).first()
        if team_doc is None:
            team_doc = Team(team_id=team_id, module=module, slug=team_key, name=name, is_mandatory=is_mandatory)
            team_doc.save()

        current_roles = {m["role"] for m in members}
        # Drop any saved role that's no longer present (e.g. removed).
        for stale in TeamMember.objects(team=team_doc):
            if stale.role not in current_roles:
                stale.delete()

        for m in members:
            mapped = [
                {"responsibility": r["text"], "action": r["action"], "detail": r["detail"], "phase": r.get("phase", "")}
                for r in resp.get(team_key, [])
                if r["who"] == m["role"]
            ]
            tm = TeamMember.objects(team=team_doc, role=m["role"]).first()
            if tm is None:
                tm = TeamMember(team=team_doc, role=m["role"])
            tm.primary_slack_user_ids = list(m["primary"])
            tm.backup_slack_user_ids = list(m["backup"])
            tm.mapped_responsibilities = mapped
            tm.save()
