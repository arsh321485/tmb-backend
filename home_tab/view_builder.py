"""
Builds the Block Kit layout shown in Slack's App Home tab (A4 in the
tracker: "upcoming drills, my open actions, my readiness, my role card").

Everything here is placeholder data for now -- once Exercise/Drill/Scoring
models exist (Exercise orchestration + Measurement & scoring domains), swap
the mock values for real queries scoped to this Slack user.
"""


def build_home_view(user) -> dict:
    """
    user: an accounts.models.User document (may be None if we don't
    recognize this Slack user yet).
    """
    display_name = user.name if user and user.name else "there"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Welcome back, {display_name} :wave:"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*:calendar: Upcoming drills*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_No drills scheduled yet._ Once cadence scheduling "
                "(E7) is built, upcoming drills for your team will show here.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*:white_check_mark: My open actions*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_Nothing outstanding._ Corrective actions assigned "
                "to you (H4) will be listed here once gap tracking is built.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*:bar_chart: My readiness*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_Not scored yet._ Your readiness score (G9) appears "
                "here after your first exercise or micro-drill.",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*:bust_in_silhouette: My role card*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_No role assigned yet._ Once plans are mapped to "
                "responders, your assigned role(s) will show here.",
            },
        },
    ]

    return {"type": "home", "blocks": blocks}
