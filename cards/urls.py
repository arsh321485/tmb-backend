from django.urls import path

from . import views

urlpatterns = [
    path("slack/", views.slack_interactivity, name="slack_interactivity"),
]
