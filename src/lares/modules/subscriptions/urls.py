from django.urls import path

from . import views

app_name = "subscriptions"

urlpatterns = [
    path("contratado/", views.subscription_list, name="list"),
]
