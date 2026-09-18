from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("dinero/", views.accounts, name="accounts"),
    path("dinero/en-que-se-va/", views.where_it_goes, name="spending"),
    path("dinero/con/<uuid:pk>/", views.merchant, name="merchant"),
    path("dinero/tarjeta/<uuid:pk>/", views.card_detail, name="card"),
    path("dinero/a-meses/nuevo/", views.installment_new, name="installment-new"),
    path("dinero/apartado/", views.provisions, name="provisions"),
    path("dinero/apartado/nuevo/", views.provision_new, name="provision-new"),
    path("dinero/apartado/<uuid:pk>/", views.provision_edit, name="provision-edit"),
    path("dinero/alcanza/", views.cash_flow, name="cash-flow"),
    path("dinero/como-estoy/", views.health, name="health"),
    path("dinero/topes/", views.budgets, name="budgets"),
    path("dinero/topes/nuevo/", views.budget_new, name="budget-new"),
    path("dinero/topes/<uuid:pk>/", views.budget_edit, name="budget-edit"),
    path("dinero/importar/", views.import_statement, name="import"),
    path("dinero/importar/confirmar/", views.import_confirm, name="import-confirm"),
]
