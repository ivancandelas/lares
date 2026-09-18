from django.urls import path

from . import views

app_name = "property"

urlpatterns = [
    path("inmuebles/", views.property_list, name="list"),
]
