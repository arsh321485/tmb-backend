from django.urls import path

from . import views

urlpatterns = [
    path("slack/", views.slack_events, name="slack_events"),
]
