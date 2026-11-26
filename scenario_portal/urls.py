from django.urls import path

from . import views

urlpatterns = [
    path("otp/request/", views.request_otp, name="scenario_portal_request_otp"),
    path("otp/verify/", views.verify_otp, name="scenario_portal_verify_otp"),
    path("scenario/", views.get_scenario, name="scenario_portal_get_scenario"),
]
