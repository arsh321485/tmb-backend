import datetime

import mongoengine as me

STATUS_UPLOADED = "uploaded"
STATUS_PARSED = "parsed"
STATUS_FAILED = "failed"

STATUS_CHOICES = (STATUS_UPLOADED, STATUS_PARSED, STATUS_FAILED)

ALLOWED_EXTENSIONS = {"docx", "pdf", "xlsx"}


class Plan(me.Document):
    """
    An uploaded continuity/incident plan document (B1: drag-and-drop plan
    intake). The raw file is stored in GridFS via FileField; parsing it
    into a structured model (B2: roles, triggers, RTO/RPO, escalation
    paths...) is separate, not-yet-built work -- `status`/`parsed_summary`
    are placeholders for that to fill in later.
    """

    filename = me.StringField(required=True)
    file_extension = me.StringField(required=True, choices=tuple(ALLOWED_EXTENSIONS))
    file_data = me.FileField(required=True)

    uploaded_by_slack_user_id = me.StringField(required=False)
    slack_team_id = me.StringField(required=False)
    slack_channel_id = me.StringField(required=False)

    # B8: plan versioning. Re-uploading a file with the same name in the
    # same channel is treated as a new version of the same plan, not an
    # unrelated document -- see plans/versioning.py.
    version = me.IntField(default=1)
    is_latest = me.BooleanField(default=True)
    superseded_at = me.DateTimeField(required=False)

    status = me.StringField(choices=STATUS_CHOICES, default=STATUS_UPLOADED)
    # Raw text pulled out of the file (plans/parsing.py). Structured
    # extraction (roles, RTO/RPO, escalation paths...) is still TODO --
    # this is just the text for that future step to run against.
    extracted_text = me.StringField(required=False)
    parse_error = me.StringField(required=False)
    # {"rto": [...], "rpo": [...], "emails": [...], "phones": [...], "sections": {...}}
    # -- see plans/structured_extraction.py. Roles/triggers/escalation paths
    # as real structured data are still open; this is pattern-matching, not NLP.
    structured_data = me.DictField(required=False)
    # [{"code": ..., "message": ...}, ...] -- see plans/gap_review.py (B4).
    gaps = me.ListField(me.DictField(), default=list)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "plans", "ordering": ["-created_at"]}
