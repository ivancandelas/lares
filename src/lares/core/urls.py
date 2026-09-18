from django.contrib.auth import views as auth_views
from django.urls import path

from . import (
    api,
    views,
    views_connectors,
    views_contacts,
    views_crud,
    views_inbox,
)

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("patrimonio/", views.holdings, name="holdings"),
    path("documentos/", views.documents, name="documents"),
    path("buscar/", views.search, name="search"),

    path("bandeja/", views_inbox.inbox, name="inbox"),
    path("bandeja/<uuid:pk>/", views_inbox.inbox_review, name="inbox-review"),
    path("bandeja/<uuid:pk>/descartar/", views_inbox.inbox_discard, name="inbox-discard"),
    path("bandeja/compartir/", views_inbox.inbox_share, name="inbox-share"),
    path("bandeja/reprocesar/", views_inbox.inbox_reclassify_all, name="inbox-reclassify-all"),
    path("bandeja/<uuid:pk>/reprocesar/", views_inbox.inbox_reclassify, name="inbox-reclassify"),
    path("bandeja/<uuid:pk>/recuperar/", views_inbox.inbox_restore, name="inbox-restore"),

    path("conectores/", views_connectors.connector_list, name="connectors"),
    path("conectores/nuevo/<str:key>/", views_connectors.connector_new, name="connector-new"),
    path("conectores/<uuid:pk>/", views_connectors.connector_edit, name="connector-edit"),
    path("conectores/<uuid:pk>/traer/", views_connectors.connector_run, name="connector-run"),

    path("calendario/", views.calendar_settings, name="calendar-settings"),
    path("calendario/<str:token>.ics", views.calendar_feed, name="calendar-feed"),
    path("o/<uuid:pk>.ics", views.obligation_ics, name="obligation-ics"),

    path("empezar/", views.onboarding, name="onboarding"),

    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service-worker"),

    path("nuevo/", views_crud.add_index, name="add"),
    path("nuevo/<str:kind>/", views_crud.resource_new, name="resource-new"),
    path("r/<uuid:pk>/", views_crud.resource_detail, name="resource-detail"),
    path("r/<uuid:pk>/editar/", views_crud.resource_edit, name="resource-edit"),
    path("r/<uuid:pk>/baja/", views_crud.resource_dispose, name="resource-dispose"),
    path("r/<uuid:pk>/comprobar/", views_crud.resource_verify, name="resource-verify"),
    path("r/<uuid:pk>/recuperar/", views_crud.resource_restore, name="resource-restore"),

    path("personas/", views_contacts.contacts, name="parties"),
    path("personas/nueva/", views_crud.party_new, name="party-new"),

    path("contactos/todos.vcf", views_contacts.all_vcards, name="contacts-vcf"),
    path("contactos/etiqueta/<slug:slug>.vcf", views_contacts.tag_vcard,
         name="tag-vcf"),
    path("personas/<uuid:pk>/contacto/", views_contacts.contact_points,
         name="contact-points"),
    path("personas/<uuid:pk>.vcf", views_contacts.party_vcard, name="party-vcf"),
    path("contacto/<uuid:pk>/quitar/", views_contacts.contact_point_delete,
         name="contact-point-delete"),

    path("compartido/", views_contacts.shares, name="shares"),
    path("compartido/nuevo/", views_contacts.share_new, name="share-new"),
    path("compartido/<uuid:pk>/revocar/", views_contacts.share_revoke,
         name="share-revoke"),
    path("c/<str:token>/", views_contacts.shared_view, name="shared"),
    path("c/<str:token>.vcf", views_contacts.shared_vcard, name="shared-vcf"),
    path("personas/<uuid:pk>/", views_crud.party_detail, name="party-detail"),
    path("personas/<uuid:pk>/editar/", views_crud.party_edit, name="party-edit"),
    path("r/<uuid:pk>/prestar/", views_crud.resource_lend, name="resource-lend"),
    path("r/<uuid:pk>/devolver/", views_crud.resource_return, name="resource-return"),

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
