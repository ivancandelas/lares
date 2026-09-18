from django.urls import path

from . import views

app_name = "leases"

urlpatterns = [
    path("arrendamiento/", views.lease_list, name="list"),
    path("arrendamiento/rendimiento/", views.yields, name="yields"),
    path("arrendamiento/<uuid:pk>/", views.lease_detail, name="detail"),
    path("arrendamiento/<uuid:pk>/deposito/", views.deposit_returned,
         name="deposit-returned"),
    path("renta/<uuid:pk>/registrar/", views.payment_register, name="payment"),
]
