from django.urls import path

from . import views

urlpatterns = [
    path("slack/", views.slack_login, name="slack_login"),
    path("slack/callback/", views.slack_callback, name="slack_callback"),
    path("teams/", views.teams_login, name="teams_login"),
    path("teams/callback/", views.teams_callback, name="teams_callback"),
    path("me/", views.me, name="me"),
]
