import mongoengine as me


class CustomTeam(me.EmbeddedDocument):
    """A team created via the 'Create a team' modal (real, not a mock suggestion)."""

    name = me.StringField(required=True)
    module = me.StringField(required=False)
    member_slack_user_ids = me.ListField(me.StringField(), default=list)


class WizardState(me.Document):
    """
    Tracks real progress through the setup wizard cards, per workspace --
    e.g. which of the suggested admins have actually been added, so
    "Add Priya" persists instead of being a no-op click.
    """

    team_id = me.StringField(required=True, unique=True)
    admins_added = me.ListField(me.StringField(), default=list)  # e.g. ["PA", "MC"]
    custom_teams = me.EmbeddedDocumentListField(CustomTeam, default=list)

    meta = {"collection": "wizard_states"}


def get_or_create_state(team_id: str) -> WizardState:
    state = WizardState.objects(team_id=team_id).first()
    if state is None:
        state = WizardState(team_id=team_id)
        state.save()
    return state
