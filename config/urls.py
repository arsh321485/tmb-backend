"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from cards.views import serve_static_asset

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/commands/", include("commands.urls")),
    path("api/events/", include("home_tab.urls")),
    path("api/interactivity/", include("cards.urls")),
    path("api/teams-portal/", include("teams_portal.urls")),
    # Real public URLs for images referenced from Slack cards (e.g. the
    # Welcome banner, and the per-role card images rendered on the fly
    # under static_assets/generated/) -- Slack fetches these itself, so
    # they need to be reachable over plain HTTPS, not a local file path.
    # <path:> (not <str:>) so a "generated/<file>.png" subpath matches too.
    path("assets/<path:filename>", serve_static_asset, name="static_asset"),
]
