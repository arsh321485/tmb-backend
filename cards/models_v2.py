"""
Real database models for the new-design flow (#testmyplan-command-center,
#ir-war-room, #privacy-bridge, testmyplan-general).

Everything here was previously only encoded into the Slack message's own
block_id strings and reconstructed on every click (see cards/*_v2.py's
read_current_state() functions) -- that state disappeared the moment the
message was deleted. This is Day 1 of turning that into a real backend:
saved to Mongo, scoped by team_id like every other model in this project.

Deliberately separate from exercises/models.py's Exercise model -- sir
said to focus on connecting the two systems later, not now.
"""

import datetime

import mongoengine as me


class AdminSetup(me.Document):
    """
    One per workspace: which threats were confirmed, and who admins each
    module. Was previously only readable by parsing the Threats/Admins
    card's own message blocks.
    """

    team_id = me.StringField(required=True, unique=True)

    # [{"module": "cyber", "threat_id": "external", "criticality": "high"}, ...]
    confirmed_threats = me.ListField(me.DictField(), default=list)
    # [{"module": "cyber", "id": "custom-1", "label": "...", "criticality": "..."}]
    custom_threats = me.ListField(me.DictField(), default=list)

    # {"cyber": "U0123", "privacy": "U0456"}
    module_admins = me.DictField(default=dict)

    # Threat Profile card's drill-down position -- which Module/
    # Criticality/Threat/Incident/Cause/Phase/Scenario tab is currently
    # open. Previously reconstructed purely by re-reading the Slack
    # message on every click (read_current_state) -- real persistence so
    # it survives beyond that one message (e.g. telling first-time-through
    # a combo apart from a repeat visit, once that feature is built).
    threat_profile_nav = me.DictField(default=dict)

    # Which (module, threat, incident, cause) combos have already had their
    # Phase/Scenario auto-defaulted once -- sir's call: Phase defaults to
    # Identification and Scenario to Trigger the FIRST time a combo is
    # reached, but not on a repeat visit (then the admin picks fresh).
    threat_profile_visited_combos = me.ListField(me.StringField(), default=list)

    updated_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "admin_setups", "strict": False}


class OrgProfile(me.Document):
    """
    "Organization Details" step -- real per-workspace answers. Sir's call
    (again): captured on the website signup form BEFORE Slack install
    (see PendingOrgProfile below + accounts/views.py), not inside Slack.
    The Slack card is now read-only display + an "Edit" modal for
    corrections, not the original collection point.
    """

    team_id = me.StringField(required=True, unique=True)

    org_name = me.StringField(required=False)
    industry = me.StringField(required=False)
    website_url = me.StringField(required=False)
    regions = me.ListField(me.StringField(), default=list)
    regulations = me.ListField(me.StringField(), default=list)

    updated_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "org_profiles", "strict": False}


class PendingOrgProfile(me.Document):
    """
    Organization Details answered on the website signup form, before the
    person has clicked "Sign up with Slack" and before we know which
    Slack workspace (team_id) they'll land in. Held here under a random
    token; accounts/views.py's slack_callback looks it up right after a
    brand-new workspace installs and copies it into the real OrgProfile
    for that team_id, then deletes this row.
    """

    token = me.StringField(required=True, unique=True)

    org_name = me.StringField(required=False)
    industry = me.StringField(required=False)
    website_url = me.StringField(required=False)
    regions = me.ListField(me.StringField(), default=list)
    regulations = me.ListField(me.StringField(), default=list)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "pending_org_profiles", "strict": False}


class Team(me.Document):
    """A response team for one module in one workspace (e.g. "Incident Response Team" for Cybersecurity)."""

    team_id = me.StringField(required=True)  # Slack team id (workspace)
    module = me.StringField(required=True)  # "cyber", "privacy", or a custom module id
    slug = me.StringField(required=True)  # stable id for this team within the module, e.g. "ir_team" or "customdraft-<n>"
    name = me.StringField(required=True)  # "Incident Response Team"
    is_mandatory = me.BooleanField(default=False)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {
        "collection": "teams",
        "indexes": [{"fields": ["team_id", "module", "slug"], "unique": True}],
        "strict": False,
    }


class TeamMember(me.Document):
    """
    One role within a team -- who's primary, who's backup, and what exact
    action each mapped responsibility means for them. A team can have more
    than one role (e.g. "IR Lead" and "SOC Analyst" both under Incident
    Response Team).
    """

    team = me.ReferenceField(Team, required=True)
    role = me.StringField(required=True)

    primary_slack_user_ids = me.ListField(me.StringField(), default=list)
    backup_slack_user_ids = me.ListField(me.StringField(), default=list)

    # [{"responsibility": "...", "action": "Decide", "detail": "..."}]
    mapped_responsibilities = me.ListField(me.DictField(), default=list)

    updated_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "team_members", "strict": False}


class ScenarioSelection(me.Document):
    """Which threat -> incident -> cause -> scenario was picked, per module, per workspace."""

    team_id = me.StringField(required=True)
    module = me.StringField(required=True)

    threat_id = me.StringField(required=False)
    incident_id = me.StringField(required=False)
    cause_id = me.StringField(required=False)
    scenario_id = me.StringField(required=False)

    # Step 6 "Arm this test" -- the plan's steps are still a fixed
    # placeholder (real per-scenario content is pending sir's sign-off),
    # but whether it's armed and ready for Step 7 to trigger is real,
    # saved state regardless of that content decision.
    armed = me.BooleanField(default=False)
    armed_at = me.DateTimeField(required=False)

    updated_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {
        "collection": "scenario_selections",
        "indexes": [{"fields": ["team_id", "module"], "unique": True}],
        "strict": False,
    }
