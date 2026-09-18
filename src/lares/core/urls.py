from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("patrimonio/", views.holdings, name="holdings"),
    path("documentos/", views.documents, name="documents"),
    path("buscar/", views.search, name="search"),
    path("entrar/", auth_views.LoginView.as_view(), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
]
