from django.contrib.auth import views as auth_views
from django.urls import path

from . import api, views, views_crud

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("patrimonio/", views.holdings, name="holdings"),
    path("documentos/", views.documents, name="documents"),
    path("buscar/", views.search, name="search"),

    path("nuevo/", views_crud.add_index, name="add"),
    path("nuevo/<str:kind>/", views_crud.resource_new, name="resource-new"),
    path("r/<uuid:pk>/", views_crud.resource_detail, name="resource-detail"),
    path("r/<uuid:pk>/editar/", views_crud.resource_edit, name="resource-edit"),

    path("personas/", views_crud.party_list, name="parties"),
    path("personas/nueva/", views_crud.party_new, name="party-new"),
    path("personas/<uuid:pk>/editar/", views_crud.party_edit, name="party-edit"),

    path("documentos/nuevo/", views_crud.document_new, name="document-new"),
    path("documentos/<uuid:pk>/editar/", views_crud.document_edit, name="document-edit"),

    path("recurrentes/", views_crud.rule_list, name="rules"),
    path("recurrentes/nuevo/", views_crud.rule_new, name="rule-new"),
    path("recurrentes/<uuid:pk>/alternar/", views_crud.rule_toggle, name="rule-toggle"),

    path("cuentas/nueva/", views_crud.account_new, name="account-new"),
    path("ubicaciones/nueva/", views_crud.location_new, name="location-new"),
    path("gastos/nuevo/", views_crud.expense_new, name="expense-new"),
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
