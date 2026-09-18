from django.urls import path

from . import views

app_name = "vehicles"

urlpatterns = [
    path("vehiculos/", views.vehicle_list, name="list"),
]
