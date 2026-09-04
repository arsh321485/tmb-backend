"""
Renders a card with real tracked state merged in, instead of the static
prototype JSON as-is. So far only the admin-team card (02) needs this --
"N added" and each "Add X" button reflecting whether that person has
actually been added (WizardState), not just always showing "0 added".
"""

from .loader import load_card
from .models import get_or_create_state

ADMIN_TEAM_CARD = "02-admin-team.json"


def build_admin_team_card(team_id: str, org_name: str = "", person_name: str = "") -> dict:
    card = load_card(ADMIN_TEAM_CARD, org_name=org_name, person_name=person_name)
    state = get_or_create_state(team_id)
    added = set(state.admins_added)

    for block in card["blocks"]:
        if block.get("type") == "context":
            for element in block.get("elements", []):
                if "added" in element.get("text", ""):
                    element["text"] = f":busts_in_silhouette: *Share the load*  ·  {len(added)} added"

        if block.get("type") == "actions":
            for button in block.get("elements", []):
                if button.get("action_id") == "admin_add" and button.get("value") in added:
                    button["text"]["text"] = "✓ Added"

    return card
