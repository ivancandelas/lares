from django.urls import path

from . import views

app_name = "taxes"

urlpatterns = [
    path("impuestos/", views.overview, name="overview"),
    path("impuestos/perfil/nuevo/", views.profile_new, name="profile-new"),
    path("impuestos/perfil/<uuid:pk>/", views.profile_detail, name="profile"),
    path("impuestos/perfil/<uuid:pk>/editar/", views.profile_edit,
         name="profile-edit"),
    path("impuestos/perfil/<uuid:pk>/paquete/", views.package, name="package"),
    path("impuestos/deducible/", views.deduction_new, name="deduction-new"),
    path("impuestos/deducible/<uuid:pk>/", views.deduction_edit,
         name="deduction-edit"),
    path("impuestos/deducible/<uuid:pk>/quitar/", views.deduction_delete,
         name="deduction-delete"),
    path("impuestos/retencion/", views.withholding_new, name="withholding-new"),
    path("impuestos/declaracion/", views.filing_new, name="filing-new"),
    path("impuestos/declaracion/<uuid:pk>/", views.filing_edit,
         name="filing-edit"),
]
