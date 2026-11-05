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

    # Which modules this org actually uses (picked on the Admins screen,
    # before assigning owners) -- e.g. ["cyber"] for an org with no
    # privacy/compliance scope. "plans_bia" isn't in this list: every org
    # needs someone owning the plan upload regardless of which modules
    # they picked.
    selected_modules = me.ListField(me.StringField(), default=lambda: ["cyber", "privacy"])

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

    # Where the Configure Teams card is currently sitting in Slack
    # ({"channel_id": ..., "message_ts": ...}) -- captured every time it's
    # (re)drawn, so a real-time event elsewhere (someone acknowledging
    # their role) can push a fresh update to it without the admin having
    # to click anything to refresh.
    teams_card_location = me.DictField(default=dict)

    # Where the Upload & Analysis card is currently sitting -- same idea
    # as teams_card_location: a DM upload finishing (plans/intake.py's
    # handle_dm_message_event, called from home_tab/views.py) pushes a
    # fresh card here instead of the admin having to manually refresh to
    # see a file that finished processing minutes ago.
    bia_upload_card_location = me.DictField(default=dict)

    # The real dedicated "testmyplan-threats-center" channel -- created
    # once per workspace the first time /testmyplan threats runs, reused
    # after that instead of creating a new channel every time.
    threats_center_channel_id = me.StringField(required=False)

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


class DraftBiaRequest(me.Document):
    """
    "No BCP, don't want GRC" path -- client asked us to generate a draft
    BIA/BCP instead of using the GRC Department option. org_name/website
    come straight from the real OrgProfile (sir's call: already captured
    at signup, never ask for it again inside Slack).

    status "requested" is set the moment they ask, "completed" once a
    real Plan exists from it, "failed" if the research subprocess
    errored, timed out, or produced nothing usable -- see
    plans/draft_generation.py. error_message is only set for "failed",
    and is what the Slack screen shows instead of leaving the user
    staring at "pending" forever with no explanation.
    """

    team_id = me.StringField(required=True, unique=True)
    org_name = me.StringField(required=False)
    website_url = me.StringField(required=False)
    status = me.StringField(choices=("requested", "completed", "failed"), default="requested")
    error_message = me.StringField(required=False)
    requested_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "draft_bia_requests", "strict": False}


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

    # {slack_user_id: datetime} -- who has actually confirmed "I understand
    # my role and I'm ready" via the real Welcome -> Role -> Acknowledge DM
    # flow (role_welcome_v2.py), keyed per person since primary and backup
    # each acknowledge independently.
    acknowledged_by = me.DictField(default=dict)

    # {slack_user_id: datetime} -- who clicked "I can't cover this role"
    # (role_welcome_v2.py's v2_role_decline) instead of acknowledging.
    # When the primary declines, their backup(s) get notified and
    # activated automatically.
    declined_by = me.DictField(default=dict)

    # {slack_user_id: "sent" | "failed"} -- whether the real Welcome DM
    # (role_welcome_v2.send_welcome_dm) actually went out when this person
    # was assigned, set from the real Slack API call's own result. Not in
    # the dict yet = DM hasn't been attempted (e.g. assignment predates
    # this field).
    dm_status = me.DictField(default=dict)

    # {slack_user_id: datetime} -- when the Welcome DM actually went out,
    # so the 24h/48h reminder check knows how long someone's been silent.
    dm_sent_at = me.DictField(default=dict)

    # {slack_user_id: ["24", "48"]} -- which reminder stages have already
    # been sent to this person, so the recurring check never re-sends the
    # same stage twice.
    reminders_sent = me.DictField(default=dict)

    # [slack_user_id, ...] -- who's already been reported to the People &
    # Roles owner as "left the workspace" for this role, so the recurring
    # leaver check never sends the same alert twice for the same person.
    leaver_notified = me.ListField(me.StringField(), default=list)

    # {primary_slack_user_id: datetime} -- a primary who went quiet
    # (not acknowledged, not declined) for ROLE_TIMEOUT_MINUTES, so
    # their backup was auto-activated by the fast timeout check
    # (cards/role_reminders_v2.py's check_backup_timeout_activation),
    # same real activation as an explicit decline, just time-triggered
    # instead of a click. Keyed separately from reminders_sent (the
    # slower 24h/48h admin-escalation path) so the two never collide.
    backup_timeout_activated = me.DictField(default=dict)

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
    phase = me.StringField(required=False)  # which Phase tab was active on Threat Profile when armed

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


STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"


class GeneratedScenario(me.Document):
    """
    A22/A23 -- one AI-written scenario (plans/scenario_generator.py) for
    a given module's Threat -> Incident -> Cause -> Phase pick, built
    from the org's real plan and real assigned roles instead of the one
    fixed ransomware story. Held here as "proposed" until the exercise
    lead reviews and approves it (A23) -- nothing here is live/sendable
    to real participants until approved=True.
    """

    team_id = me.StringField(required=True)
    module = me.StringField(required=True)
    threat_id = me.StringField(required=False)
    incident_id = me.StringField(required=False)
    cause_id = me.StringField(required=False)
    threat_label = me.StringField(required=False)
    incident_name = me.StringField(required=False)
    cause_name = me.StringField(required=False)
    phases = me.ListField(me.StringField(), default=list)

    # [{"inject_id","type","phase","seq","title","target_role",
    #   "inject_message","decision_id","decision_question",
    #   "options":[{"option","option_text","score","rating","feedback","triggers_inject"}]}]
    injects = me.ListField(me.DictField(), default=list)
    # [{"inject_id","type","phase","title","target_role","inject_message"}]
    consequence_injects = me.ListField(me.DictField(), default=list)

    status = me.StringField(choices=(STATUS_PROPOSED, STATUS_APPROVED), default=STATUS_PROPOSED)
    approved_by_slack_user_id = me.StringField(required=False)
    approved_at = me.DateTimeField(required=False)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "generated_scenarios", "ordering": ["-created_at"], "strict": False}


RUN_STATUS_SCHEDULED = "scheduled"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"


class AIExerciseRun(me.Document):
    """
    A23/A24 -- one real live run of an approved GeneratedScenario.

    Deliberately its own separate collection, NOT exercises.models.Exercise
    -- that model and its background firing/escalation logic
    (exercises/drill.py, exercises/apps.py) are shared by the 3 real
    pre-built drills (RW-01/02/03) and are left untouched on purpose, so
    an AI-generated run can never collide with or be picked up by that
    existing engine. This is a fully independent, parallel path that
    happens to produce the same real experience for participants.
    """

    team_id = me.StringField(required=True)
    scenario = me.ReferenceField(GeneratedScenario, required=True)

    trigger_type = me.StringField(required=False)  # "now" / "scheduled" / "surprise"
    # Training mode (flowchart's Yes/No branch): True -> everyone got a
    # real pre-notification DM before this run started. False -> sent
    # directly, no warning, same as every run before this field existed.
    training_mode = me.BooleanField(default=False)
    status = me.StringField(choices=(RUN_STATUS_SCHEDULED, RUN_STATUS_RUNNING, RUN_STATUS_COMPLETED), default=RUN_STATUS_SCHEDULED)
    scheduled_at = me.DateTimeField(required=False)

    # Position in scenario.injects (by seq) the run is currently waiting
    # on -- None once every Main inject has been resolved.
    current_seq = me.IntField(required=False)

    started_by_slack_user_id = me.StringField(required=False)
    # Where the Trigger/Schedule button was clicked from -- so the report
    # can be posted back there automatically once the run completes,
    # instead of just sitting in the database with nowhere shown for it.
    origin_channel_id = me.StringField(required=False)
    started_at = me.DateTimeField(required=False)
    ended_at = me.DateTimeField(required=False)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "ai_exercise_runs", "ordering": ["-created_at"], "strict": False}


class AIDecisionResponse(me.Document):
    """One real answer to one real AI-generated inject's decision --
    separate collection from exercises.models.DecisionResponse for the
    same isolation reason as AIExerciseRun."""

    run = me.ReferenceField(AIExerciseRun, required=True)
    inject_id = me.StringField(required=True)
    decision_id = me.StringField(required=True)
    assigned_slack_user_id = me.StringField(required=True)
    target_role = me.StringField(required=False)

    chosen_option = me.StringField(required=False)
    score = me.IntField(required=False)
    rating = me.StringField(required=False)
    triggers_inject = me.StringField(required=False)

    slack_channel_id = me.StringField(required=False)
    slack_message_ts = me.StringField(required=False)

    sent_at = me.DateTimeField(default=datetime.datetime.utcnow)
    responded_at = me.DateTimeField(required=False)

    meta = {"collection": "ai_decision_responses", "ordering": ["sent_at"], "strict": False}
