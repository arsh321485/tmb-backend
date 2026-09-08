import mongoengine as me


class CustomTeam(me.EmbeddedDocument):
    """A team created via the 'Create a team' modal (real, not a mock suggestion)."""

    name = me.StringField(required=True)
    module = me.StringField(required=False)
    member_slack_user_ids = me.ListField(me.StringField(), default=list)
    # [{"role": "IR Lead", "member": "<slack_user_id>"}, ...] -- per-person
    # role, matching the design's intent (member_slack_user_ids alone loses
    # which role each person was assigned).
    role_assignments = me.ListField(me.DictField(), default=list)


class WizardState(me.Document):
    """
    Tracks real progress through the setup wizard cards, per workspace --
    e.g. which of the suggested admins have actually been added, so
    "Add Priya" persists instead of being a no-op click.
    """

    team_id = me.StringField(required=True, unique=True)
    # {"PA": "Cybersecurity", "MC": "All modules"} -- which module each
    # confirmed admin is responsible for. Presence as a key = confirmed.
    admin_modules = me.DictField(default=dict)
    # ["SR", "TK", ...] -- suggested response team members actually added
    # (real people can't be genuinely DM'd since these are mock names, but
    # the "added"/"notified" status is tracked for real).
    response_members_added = me.ListField(me.StringField(), default=list)
    custom_teams = me.EmbeddedDocumentListField(CustomTeam, default=list)
    # True right after "Upload BIA" is clicked, until a real file is
    # actually dropped in the channel and parsed -- see
    # home_tab/views.py's _maybe_complete_bia_upload.
    awaiting_bia = me.BooleanField(default=False)

    # strict=False: tolerate old field names left over in already-saved
    # documents from before a schema change (e.g. admins_added ->
    # admin_modules), instead of crashing every read for that workspace.
    meta = {"collection": "wizard_states", "strict": False}


def get_or_create_state(team_id: str) -> WizardState:
    state = WizardState.objects(team_id=team_id).first()
    if state is None:
        state = WizardState(team_id=team_id)
        state.save()
    return state
