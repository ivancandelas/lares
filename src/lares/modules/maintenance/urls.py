from django.urls import path

from . import views

app_name = "maintenance"

urlpatterns = [
    path("mantenimiento/", views.overview, name="list"),
    path("mantenimiento/plan/nuevo/", views.plan_new, name="plan-new"),
    path("mantenimiento/plan/<uuid:pk>/", views.plan_edit, name="plan-edit"),
    path("mantenimiento/trabajo/nuevo/", views.work_new, name="work-new"),
    path("proveedores/", views.provider_list, name="providers"),
]
