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


def load_admins_state(team_id: str) -> dict:
    setup = AdminSetup.objects(team_id=team_id).first()
    assigned = dict(setup.module_admins) if setup else {}
    return {"assigned": assigned, "expanded": None, "delegate_pick": None}


def save_admins_state(team_id: str, assigned: dict) -> None:
    setup = _get_or_create(team_id)
    setup.module_admins = dict(assigned)
    setup.save()


def load_scenario_selection(team_id: str, module: str) -> dict:
    sel = ScenarioSelection.objects(team_id=team_id, module=module).first()
    if sel is None:
        return {"threat_id": "", "incident_id": "", "cause_id": "", "scenario_id": "", "armed": False, "armed_at": None}
    return {
        "threat_id": sel.threat_id or "",
        "incident_id": sel.incident_id or "",
        "cause_id": sel.cause_id or "",
        "scenario_id": sel.scenario_id or "",
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
