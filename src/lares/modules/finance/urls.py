from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("dinero/", views.accounts, name="accounts"),
    path("dinero/en-que-se-va/", views.where_it_goes, name="spending"),
    path("dinero/resultado/", views.statement, name="statement"),
    path("dinero/con/<uuid:pk>/", views.merchant, name="merchant"),
    path("dinero/tarjeta/<uuid:pk>/", views.card_detail, name="card"),
    path("dinero/a-meses/nuevo/", views.installment_new, name="installment-new"),
    path("dinero/apartado/", views.provisions, name="provisions"),
    path("dinero/apartado/nuevo/", views.provision_new, name="provision-new"),
    path("dinero/apartado/<uuid:pk>/", views.provision_edit, name="provision-edit"),
    path("dinero/alcanza/", views.cash_flow, name="cash-flow"),
    path("dinero/como-estoy/", views.health, name="health"),
    path("dinero/ingresos/nuevo/", views.income_new, name="income-new"),
    path("dinero/ingresos/<uuid:pk>/", views.income_edit, name="income-edit"),
    path("dinero/presupuesto/", views.plans, name="plans"),
    path("dinero/presupuesto/nuevo/", views.plan_new, name="plan-new"),
    path("dinero/presupuesto/<uuid:pk>/", views.plan_detail, name="plan"),
    path("dinero/presupuesto/<uuid:pk>/editar/", views.plan_edit,
         name="plan-edit"),
    path("dinero/presupuesto/<uuid:pk>/categoria/", views.plan_line_new,
         name="plan-line-new"),
    path("dinero/presupuesto/<uuid:pk>/partir/", views.plan_seed,
         name="plan-seed"),
    path("dinero/presupuesto/linea/<uuid:pk>/", views.plan_line_edit,
         name="plan-line-edit"),
    path("dinero/topes/", views.budgets, name="budgets"),
    path("dinero/importar/", views.import_statement, name="import"),
    path("dinero/importar/confirmar/", views.import_confirm, name="import-confirm"),
]
