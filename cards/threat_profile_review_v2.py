"""
Agent 1 review/approve screen -- shows the org-specific threat list
plans/threat_profile_generator.py produced from Organization Details,
lets the admin remove any entry or add their own, then Approve.

This is a NEW screen, separate from threats_v2_data.py's fixed-4
Threat Profile drill-down (Module -> Threat -> Incident -> Cause ->
Phase -> Scenario) -- that screen still exists and still works exactly
as before. This one is the step BEFORE it: deciding which threats this
org even has. Wiring this list into the drill-down screen so the
approved threats actually drive it is a separate next step, not done
here (sir's call: see the real generated list and the approval
mechanics first).
"""

import json

from .models_v2 import OrgThreatProfile

CALLBACK_ID_ADD = "v2_tpreview_add_modal"
CALLBACK_ID_EDIT = "v2_tpreview_edit_modal"

CRIT_EMOJI = {"Critical": "🟫", "High": "🟥", "Med": "🟨"}
ADD_CRIT_CHOICES = ["Critical", "High", "Med"]
ADD_MODULE_CHOICES = ["Cybersecurity", "Privacy"]
LIKELIHOOD_CHOICES = ["High", "Medium-High", "Medium", "Low-Medium", "Low"]


def ensure_profile(team_id: str) -> OrgThreatProfile | None:
    """Loads the existing draft/approved profile for team_id, or runs
    Agent 1 to generate one for the first time if none exists yet.
    Returns None only if generation was needed and failed (e.g. no org
    profile yet, or both AI providers failed) -- never raises."""
    existing = OrgThreatProfile.objects(team_id=team_id).first()
    if existing is not None:
        return existing

    from plans.threat_profile_generator import generate_threat_profile

    threats = generate_threat_profile(team_id)
    if threats is None:
        return None

    profile = OrgThreatProfile(team_id=team_id, threats=threats, status="draft")
    profile.save()
    return profile


def _risk_matrix_blocks(threats: list[dict]) -> list[dict]:
    """Read-only Threat Category / Likelihood / Business Impact / Overall
    Risk, as Slack's own 2-column field grid -- confirmed with the admin
    this is the closest real option to an actual table Slack supports
    (`fields` only ever wraps 2-per-row, so 4 fields becomes 2 rows of
    2 instead of one row of 4 -- a real platform limit, not a style
    choice). A divider between each threat keeps that 2x2 stack reading
    as one distinct row per threat instead of blurring into the next."""
    blocks = []
    for i, t in enumerate(threats):
        emoji = CRIT_EMOJI.get(t.get("default_crit", "Med"), "🟡")
        if i > 0:
            blocks.append({"type": "divider"})
        # Two separate blocks, not one 4-field block -- Slack only adds
        # its real visual gap BETWEEN blocks, never between the 2
        # field-pairs inside a single one, which is why this used to
        # look like one squashed-together row instead of two.
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Threat Category*\n{t.get('label', '')}"},
                    {"type": "mrkdwn", "text": f"*Likelihood*\n{t.get('likelihood', 'Medium')}"},
                ],
            }
        )
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Business Impact*\n{t.get('business_impact', 'Not specified')}"},
                    {"type": "mrkdwn", "text": f"*Overall Risk*\n{emoji} {t.get('default_crit', 'Med')}"},
                ],
            }
        )
    return blocks


def _select_option(value: str, label: str | None = None) -> dict:
    return {"text": {"type": "plain_text", "text": label or value}, "value": value}


def read_active_module(message_blocks: list) -> str:
    """Whichever module tab is currently selected on the real message,
    so clicking Remove/Add/Regenerate on one tab doesn't silently bounce
    back to the first module -- same block-reading pattern every other
    v2 card uses instead of a separate persisted field for this."""
    for block in message_blocks or []:
        if block.get("type") != "actions":
            continue
        for el in block.get("elements", []):
            action_id = el.get("action_id", "")
            if action_id.startswith("v2_tpreview_module_tab__") and el.get("style") == "primary":
                return el.get("value", "")
    return ""


def build_review_card(team_id: str, active_module: str = "") -> dict:
    profile = ensure_profile(team_id)

    if profile is None:
        return {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": ":dart: Your threat profile", "emoji": True}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "Couldn't generate a threat profile yet -- make sure Organization Details "
                            "(industry, at least) is filled in, then try again."
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "↻ Try again", "emoji": True},
                            "action_id": "v2_tpreview_retry",
                            "value": "retry",
                        }
                    ],
                },
            ]
        }

    approved = profile.status == "approved"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": ":dart: Your threat profile", "emoji": True}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        ":large_green_circle: *Approved* -- this is your organization's active threat profile."
                        if approved
                        else ":white_circle: *Draft* -- generated from your Organization Details. Review, remove or add threats, then Approve."
                    ),
                }
            ],
        },
        {"type": "divider"},
    ]

    module_icon = {"Cybersecurity": ":shield:", "Privacy": ":lock:"}
    modules_present = [m for m in ADD_MODULE_CHOICES if any(t.get("module") == m for t in profile.threats)]
    if active_module not in modules_present:
        active_module = modules_present[0] if modules_present else ""

    if modules_present:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": f"{module_icon.get(m, '')} {m} ({sum(1 for t in profile.threats if t.get('module') == m)})",
                            "emoji": True,
                        },
                        "action_id": f"v2_tpreview_module_tab__{m}",
                        "value": m,
                        **({"style": "primary"} if m == active_module else {}),
                    }
                    for m in modules_present
                ],
            }
        )
        blocks.append({"type": "divider"})

    shown_threats = [t for t in profile.threats if t.get("module") == active_module]

    if shown_threats:
        # Same severity-count summary the Threat Mapping screen already
        # shows under its module tabs -- Threat Approval didn't have one
        # at all, so there was no quick read of the module's spread
        # without counting rows by eye. Only 3 real levels exist here
        # (no separate "Low" tier -- Med is the lowest Agent 1 assigns).
        counts = {"Critical": 0, "High": 0, "Med": 0}
        for t in shown_threats:
            counts[t.get("default_crit", "Med")] = counts.get(t.get("default_crit", "Med"), 0) + 1
        count_text = "  |  ".join(f"{CRIT_EMOJI[c]} {counts[c]} {c}" for c in ("Critical", "High", "Med"))
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": count_text}]})
        blocks.append({"type": "divider"})
        blocks.extend(_risk_matrix_blocks(shown_threats))
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No threats in this module._"}})

    blocks.append({"type": "divider"})

    if not approved:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "+ Add a threat", "emoji": True},
                        "action_id": "v2_tpreview_add",
                        "value": "add",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Edit", "emoji": True},
                        "action_id": "v2_tpreview_edit",
                        "value": active_module,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve → Continue to Upload & Analysis", "emoji": True},
                        "action_id": "v2_tpreview_approve",
                        "value": "approve",
                        "style": "primary",
                    },
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
                        "text": {"type": "plain_text", "text": "Edit again", "emoji": True},
                        "action_id": "v2_tpreview_reopen",
                        "value": "reopen",
                    },
                ],
            }
        )

    return {"blocks": blocks}


def build_edit_modal_view(team_id: str, active_module: str, channel_id: str, message_ts: str) -> dict:
    """Every threat, both modules, in one place -- change severity and/or
    check it for removal, all from the one Edit button instead of
    separate controls scattered on the main screen. active_module is
    only carried through so the main screen reopens on the same tab
    afterward, not used to filter what's shown here."""
    profile = OrgThreatProfile.objects(team_id=team_id).first()
    threats = profile.threats if profile else []

    blocks = []
    if threats:
        for t in threats:
            key = t.get("key", "")
            crit = t.get("default_crit", "Med")
            blocks.append(
                {
                    "type": "section",
                    "block_id": f"severity__{key}",
                    "text": {"type": "mrkdwn", "text": f"*{t.get('label', '')}*\n_{t.get('module', 'Cybersecurity')}_"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "value",
                        "options": [_select_option(c) for c in ADD_CRIT_CHOICES],
                        "initial_option": _select_option(crit) if crit in ADD_CRIT_CHOICES else _select_option("Med"),
                    },
                }
            )
        blocks.append(
            {
                "type": "input",
                "block_id": "remove_keys",
                "optional": True,
                "label": {"type": "plain_text", "text": "Check any threats to remove"},
                "element": {
                    "type": "checkboxes",
                    "action_id": "value",
                    "options": [
                        _select_option(t.get("key", ""), f"[{t.get('module', '')}] {t.get('label', '')}") for t in threats
                    ],
                },
            }
        )
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "_No threats to edit yet._"}})

    return {
        "type": "modal",
        "callback_id": CALLBACK_ID_EDIT,
        "private_metadata": json.dumps({"channel_id": channel_id, "message_ts": message_ts, "module": active_module}),
        "title": {"type": "plain_text", "text": "Edit threats"},
        "submit": {"type": "plain_text", "text": "Save changes"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_add_modal_view(channel_id: str, message_ts: str) -> dict:
    return {
        "type": "modal",
        "callback_id": CALLBACK_ID_ADD,
        "private_metadata": json.dumps({"channel_id": channel_id, "message_ts": message_ts}),
        "title": {"type": "plain_text", "text": "Add a threat"},
        "submit": {"type": "plain_text", "text": "Add"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "label",
                "label": {"type": "plain_text", "text": "Threat name"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "e.g. Third-party vendor compromise"},
                },
            },
            {
                "type": "input",
                "block_id": "module",
                "label": {"type": "plain_text", "text": "Module"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [_select_option(o) for o in ADD_MODULE_CHOICES],
                    "initial_option": _select_option(ADD_MODULE_CHOICES[0]),
                },
            },
            {
                "type": "input",
                "block_id": "likelihood",
                "label": {"type": "plain_text", "text": "Likelihood"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [_select_option(o) for o in LIKELIHOOD_CHOICES],
                    "initial_option": _select_option(LIKELIHOOD_CHOICES[2]),
                },
            },
            {
                "type": "input",
                "block_id": "business_impact",
                "label": {"type": "plain_text", "text": "Business impact"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "e.g. Severe (Financial/Data Loss), Medium (Reputational)"},
                },
            },
            {
                "type": "input",
                "block_id": "default_crit",
                "label": {"type": "plain_text", "text": "Overall risk rating"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "options": [_select_option(o) for o in ADD_CRIT_CHOICES],
                    "initial_option": _select_option(ADD_CRIT_CHOICES[1]),
                },
            },
            {
                "type": "input",
                "block_id": "why",
                "label": {"type": "plain_text", "text": "Why does this apply to you?"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "e.g. We rely on a single third-party payment processor."},
                },
            },
        ],
    }


def remove_threat(team_id: str, key: str) -> None:
    profile = OrgThreatProfile.objects(team_id=team_id).first()
    if profile is None:
        return
    profile.threats = [t for t in profile.threats if t.get("key") != key]
    profile.save()


def set_criticality(team_id: str, key: str, crit: str) -> None:
    if crit not in ADD_CRIT_CHOICES:
        return
    profile = OrgThreatProfile.objects(team_id=team_id).first()
    if profile is None:
        return
    updated_threats = []
    for t in profile.threats:
        if t.get("key") == key:
            t = dict(t)
            t["default_crit"] = crit
        updated_threats.append(t)
    profile.threats = updated_threats
    profile.save()


def add_threat(team_id: str, label: str, module: str, default_crit: str, why: str, likelihood: str = "", business_impact: str = "") -> None:
    profile = OrgThreatProfile.objects(team_id=team_id).first()
    if profile is None:
        profile = OrgThreatProfile(team_id=team_id, threats=[], status="draft")

    key = "custom_" + "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")
    existing_keys = {t.get("key") for t in profile.threats}
    suffix = 1
    base_key = key
    while key in existing_keys:
        suffix += 1
        key = f"{base_key}_{suffix}"

    profile.threats.append(
        {
            "key": key,
            "module": module if module in ADD_MODULE_CHOICES else "Cybersecurity",
            "icon": ":shield:" if module == "Cybersecurity" else ":lock:",
            "label": label,
            "why": why or "Added by you.",
            "likelihood": likelihood if likelihood in LIKELIHOOD_CHOICES else "Medium",
            "business_impact": (business_impact or "Not specified -- added manually.").strip(),
            "default_crit": default_crit if default_crit in ADD_CRIT_CHOICES else "Med",
            "source": "custom",
        }
    )
    profile.save()


def regenerate_profile(team_id: str) -> OrgThreatProfile | None:
    from plans.threat_profile_generator import generate_threat_profile

    threats = generate_threat_profile(team_id)
    if threats is None:
        return None

    profile = OrgThreatProfile.objects(team_id=team_id).first() or OrgThreatProfile(team_id=team_id)
    profile.threats = threats
    profile.status = "draft"
    profile.approved_at = None
    profile.save()
    return profile


def approve_profile(team_id: str) -> None:
    import datetime

    OrgThreatProfile.objects(team_id=team_id).update(set__status="approved", set__approved_at=datetime.datetime.utcnow())


def reopen_profile(team_id: str) -> None:
    OrgThreatProfile.objects(team_id=team_id).update(set__status="draft", unset__approved_at=1)


def ensure_threat_map(team_id: str, key: str) -> list[dict]:
    """
    Returns this threat's incident/cause tree, generating and caching
    it (into OrgThreatProfile.threats, on the matching threat's
    "incidents" field) the first time it's drilled into -- so clicking
    the same threat twice doesn't call the AI twice. Returns [] if
    there's no such threat or generation failed (never raises); the
    Threat Profile screen already handles an empty incidents list as
    "nothing mapped yet".
    """
    profile = OrgThreatProfile.objects(team_id=team_id).first()
    if profile is None:
        return []

    threat = next((t for t in profile.threats if t.get("key") == key), None)
    if threat is None:
        return []

    cached = threat.get("incidents")
    if isinstance(cached, list) and cached:
        return cached

    from plans.threat_map_generator import generate_threat_map

    incidents = generate_threat_map(threat.get("label", ""), threat.get("module", "Cybersecurity"), threat.get("why", ""), team_id=team_id)
    if not incidents:
        return []

    updated_threats = []
    for t in profile.threats:
        if t.get("key") == key:
            t = dict(t)
            t["incidents"] = incidents
        updated_threats.append(t)
    profile.threats = updated_threats
    profile.save()
    return incidents


def resolve_names(team_id: str, module: str, threat_key: str, incident_id: str, cause_id: str) -> tuple[str, str, str]:
    """
    Threat/incident/cause display names for a (module, threat, incident,
    cause) combo, whichever taxonomy it came from -- the old fixed one
    (threat_map_v2_data.py) or Agent 1's approved profile (this module's
    ensure_threat_map cache). Falls back to the raw ids themselves if
    neither has it, so a label is never blank.
    """
    from .threat_map_v2_data import _find_threat

    taxonomy_threat = _find_threat(module, threat_key) if module and threat_key else None
    if taxonomy_threat:
        incident = next((i for i in taxonomy_threat.get("incidents", []) if i["id"] == incident_id), None)
        cause = next((c for c in (incident or {}).get("causes", []) if c["id"] == cause_id), None) if incident else None
        return (
            taxonomy_threat.get("label", threat_key),
            incident.get("name", incident_id) if incident else incident_id,
            cause.get("name", cause_id) if cause else cause_id,
        )

    profile = OrgThreatProfile.objects(team_id=team_id).first() if team_id else None
    threat = next((t for t in (profile.threats if profile else []) if t.get("key") == threat_key), None)
    if not threat:
        return threat_key, incident_id, cause_id

    incidents = threat.get("incidents") or []
    incident = next((i for i in incidents if i.get("id") == incident_id), None)
    cause = next((c for c in (incident or {}).get("causes", []) if c.get("id") == cause_id), None) if incident else None
    return (
        threat.get("label", threat_key),
        incident.get("name", incident_id) if incident else incident_id,
        cause.get("name", cause_id) if cause else cause_id,
    )


def handle_edit_submission(payload: dict, bot_token: str) -> None:
    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    module = meta.get("module", "")
    team_id = payload.get("team", {}).get("id", "")

    values = view.get("state", {}).get("values", {})

    if team_id:
        for block_id, block_values in values.items():
            if not block_id.startswith("severity__"):
                continue
            key = block_id.removeprefix("severity__")
            new_crit = (block_values.get("value", {}).get("selected_option") or {}).get("value", "")
            if key and new_crit:
                set_criticality(team_id, key, new_crit)

    checked = (values.get("remove_keys", {}).get("value", {}).get("selected_options") or [])
    for opt in checked:
        key = opt.get("value", "")
        if key and team_id:
            remove_threat(team_id, key)

    if not (channel_id and message_ts and bot_token and team_id):
        return

    import requests

    from .nav_v2 import with_nav_bar_v2

    card = with_nav_bar_v2(build_review_card(team_id, active_module=module), "threat_review")
    requests.post(
        "https://slack.com/api/chat.update",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "ts": message_ts, **card},
        timeout=10,
    )


def handle_submission(payload: dict, bot_token: str) -> None:
    view = payload.get("view", {})
    try:
        meta = json.loads(view.get("private_metadata") or "{}")
    except (ValueError, TypeError):
        meta = {}
    channel_id = meta.get("channel_id", "")
    message_ts = meta.get("message_ts", "")
    team_id = payload.get("team", {}).get("id", "")

    values = view.get("state", {}).get("values", {})
    label = (values.get("label", {}).get("value", {}).get("value") or "").strip()
    module_sel = values.get("module", {}).get("value", {}).get("selected_option") or {}
    likelihood_sel = values.get("likelihood", {}).get("value", {}).get("selected_option") or {}
    business_impact = (values.get("business_impact", {}).get("value", {}).get("value") or "").strip()
    crit_sel = values.get("default_crit", {}).get("value", {}).get("selected_option") or {}
    why = (values.get("why", {}).get("value", {}).get("value") or "").strip()

    if not label or not team_id:
        return

    add_threat(
        team_id, label, module_sel.get("value", ""), crit_sel.get("value", ""), why,
        likelihood=likelihood_sel.get("value", ""), business_impact=business_impact,
    )

    if not (channel_id and message_ts and bot_token):
        return

    import requests

    from .nav_v2 import with_nav_bar_v2

    card = with_nav_bar_v2(build_review_card(team_id, active_module=module_sel.get("value", "")), "threat_review")
    requests.post(
        "https://slack.com/api/chat.update",
        headers={"Authorization": f"Bearer {bot_token}"},
        json={"channel": channel_id, "ts": message_ts, **card},
        timeout=10,
    )
