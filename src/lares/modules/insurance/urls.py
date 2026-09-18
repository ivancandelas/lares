from django.urls import path

from . import views

app_name = "insurance"

urlpatterns = [
    path("seguros/", views.policy_list, name="list"),
]
