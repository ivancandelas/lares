from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("dinero/", views.accounts, name="accounts"),
    path("dinero/en-que-se-va/", views.where_it_goes, name="spending"),
    path("dinero/con/<uuid:pk>/", views.merchant, name="merchant"),
]
