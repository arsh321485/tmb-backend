"""
Loads the Block Kit card JSON designed by the frontend team (see
`slack_cards/README.md` for the design source) so backend code can post
them to Slack. These files are the "how it should look"; posting them
with real data (instead of the mock "Veridian Health" placeholders) is
what the rest of this app does.
"""

import json
from pathlib import Path

BLOCKS_DIR = Path(__file__).parent / "blocks"


class CardNotFound(Exception):
    pass


# The prototype's mock data -- swap these for real values when posting.
PLACEHOLDER_ORG = "Veridian Health"
PLACEHOLDER_PERSON = "Alex Morgan"


def load_card(filename: str, org_name: str = "", person_name: str = "") -> dict:
    """
    filename like "01-welcome.json" or "war-rooms/01-ir-channel-created.json".
    Returns the parsed JSON as a dict. If org_name/person_name are given,
    replaces the prototype's mock names ("Veridian Health", "Alex Morgan")
    with real ones -- a simple text substitution, not a template engine,
    since the cards are mock data throughout, not just those two fields.
    """
    path = BLOCKS_DIR / filename
    if not path.exists():
        raise CardNotFound(filename)

    text = path.read_text(encoding="utf-8")
    if org_name:
        text = text.replace(PLACEHOLDER_ORG, org_name)
    if person_name:
        # Cards use both the full name ("Alex Morgan") and just the first
        # name ("Alex") depending on context -- replace the full name
        # first so the shorter one doesn't partially match inside it.
        first_name = person_name.split()[0]
        text = text.replace(PLACEHOLDER_PERSON, person_name)
        text = text.replace(PLACEHOLDER_PERSON.split()[0], first_name)

    return json.loads(text)
