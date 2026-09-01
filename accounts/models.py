import datetime

import mongoengine as me


class SlackAccount(me.EmbeddedDocument):
    slack_user_id = me.StringField(required=True)
    team_id = me.StringField(required=True)
    team_name = me.StringField()
    access_token = me.StringField(required=True)
    linked_at = me.DateTimeField(default=datetime.datetime.utcnow)


class TeamsAccount(me.EmbeddedDocument):
    aad_object_id = me.StringField(required=True)  # Azure AD user object id
    tenant_id = me.StringField(required=True)
    access_token = me.StringField(required=True)
    refresh_token = me.StringField(required=False)
    linked_at = me.DateTimeField(default=datetime.datetime.utcnow)


class User(me.Document):
    """
    A user of the app. Created the first time someone signs up via Slack or
    Teams (or, later, email). One user can have a Slack account and/or a
    Teams account linked, matched by email.
    """

    email = me.EmailField(required=True, unique=True)
    name = me.StringField(max_length=255)
    avatar_url = me.URLField(required=False)

    slack_account = me.EmbeddedDocumentField(SlackAccount, required=False)
    teams_account = me.EmbeddedDocumentField(TeamsAccount, required=False)

    created_at = me.DateTimeField(default=datetime.datetime.utcnow)
    updated_at = me.DateTimeField(default=datetime.datetime.utcnow)

    meta = {"collection": "users"}

    def save(self, *args, **kwargs):
        self.updated_at = datetime.datetime.utcnow()
        return super().save(*args, **kwargs)
