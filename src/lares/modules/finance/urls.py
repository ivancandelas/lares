from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("dinero/", views.accounts, name="accounts"),
]
