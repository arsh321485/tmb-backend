import datetime

import mongoengine as me


class ProcessedSlackEvent(me.Document):
    """
    Slack retries an Events API webhook if it doesn't get a 200 response
    within ~3 seconds -- which happens easily once a handler does real work
    (downloading + parsing a file, calling views.publish, etc). Each event
    carries a unique event_id, including retries of the same event, so we
    record IDs we've already handled and skip them the second time.
    """

    event_id = me.StringField(required=True, unique=True)
    received_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "processed_slack_events"}
