from django.contrib.auth import views as auth_views
from django.urls import path

from . import api, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("patrimonio/", views.holdings, name="holdings"),
    path("documentos/", views.documents, name="documents"),
    path("buscar/", views.search, name="search"),
    path("api/v1/agenda", api.agenda, name="api-agenda"),
    path("api/v1/obligations", api.obligations, name="api-obligations"),
    path("api/v1/obligations/<uuid:pk>/complete", api.complete_obligation,
         name="api-obligation-complete"),
    path("api/v1/resources", api.resources, name="api-resources"),
    path("api/v1/documents", api.documents, name="api-documents"),
    path("api/v1/gaps", api.gaps, name="api-gaps"),
    path("api/v1/search", api.search, name="api-search"),
    path("api/v1/webhooks", api.webhooks, name="api-webhooks"),

    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
]
