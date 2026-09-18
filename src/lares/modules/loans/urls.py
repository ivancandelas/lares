from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("prestamos/", views.loan_list, name="list"),
    path("prestamos/<uuid:pk>/", views.loan_detail, name="detail"),
    path("prestamos/<uuid:pk>/abono/", views.payment_new, name="payment-new"),
    path("prestamos/<uuid:pk>/perdonar/", views.forgive, name="forgive"),
]
