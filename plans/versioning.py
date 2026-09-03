"""
B8: plan versioning. "Every drill is stamped with the plan version it
tested. A plan change triggers a re-test recommendation."

The re-test *trigger* against actual exercises isn't wired up yet (that
needs the Exercise <-> Plan link, which doesn't exist yet) -- what's here
is the versioning half: detecting that a re-upload is a new version of an
existing plan (same filename, same channel) rather than an unrelated one,
numbering it accordingly, and marking the old version superseded.
"""

import datetime


def assign_version(plan) -> bool:
    """
    Call on an unsaved `plan` (before plan.save()). Sets plan.version and
    plan.is_latest, and marks any previous latest version of the same plan
    (by filename + channel) as superseded. Returns True if this replaced
    an earlier version (i.e. a re-test recommendation is warranted).
    """
    from .models import Plan

    previous = Plan.objects(
        filename=plan.filename,
        slack_channel_id=plan.slack_channel_id,
        is_latest=True,
    ).first()

    if previous is None:
        plan.version = 1
        plan.is_latest = True
        return False

    plan.version = previous.version + 1
    plan.is_latest = True

    previous.is_latest = False
    previous.superseded_at = datetime.datetime.utcnow()
    previous.save()

    return True
