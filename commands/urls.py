from django.urls import path

from . import views

urlpatterns = [
    path("slack/", views.slack_command, name="slack_command"),
    path("teams/", views.teams_command, name="teams_command"),
]
