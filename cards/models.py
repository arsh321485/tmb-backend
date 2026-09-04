import mongoengine as me


class WizardState(me.Document):
    """
    Tracks real progress through the setup wizard cards, per workspace --
    e.g. which of the suggested admins have actually been added, so
    "Add Priya" persists instead of being a no-op click.
    """

    team_id = me.StringField(required=True, unique=True)
    admins_added = me.ListField(me.StringField(), default=list)  # e.g. ["PA", "MC"]

    meta = {"collection": "wizard_states"}


def get_or_create_state(team_id: str) -> WizardState:
    state = WizardState.objects(team_id=team_id).first()
    if state is None:
        state = WizardState(team_id=team_id)
        state.save()
    return state
