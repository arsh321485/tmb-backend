from django.urls import path

from . import views

urlpatterns = [
    path("otp/request/", views.request_otp, name="teams_portal_request_otp"),
    path("otp/verify/", views.verify_otp, name="teams_portal_verify_otp"),
    path("members/", views.get_members, name="teams_portal_get_members"),
    path("teams/", views.get_teams, name="teams_portal_get_teams"),
    path("teams/assign/", views.set_role_assignment, name="teams_portal_set_role_assignment"),
    path("teams/apply-same-user/", views.apply_same_user, name="teams_portal_apply_same_user"),
    path("teams/remove/", views.remove_role_assignment, name="teams_portal_remove_role_assignment"),
]
