from django.urls import path

from . import views

app_name = "belongings"

urlpatterns = [
    path("objetos/", views.belonging_list, name="list"),
]
