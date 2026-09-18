"""Historial de ejemplo: planes y trabajos ya hechos."""

import datetime as dt

from django.contrib.contenttypes.models import ContentType

from lares.core.models import Party
from lares.core.models.resource import Resource

from .models import MaintenancePlan, WorkOrder


def seed(household) -> str:
    hoy = dt.date.today()
    casa = Resource.objects.filter(household=household,
                                   name="Casa de Providencia").first()
    mazda = Resource.objects.filter(household=household, name="Mazda CX-5").first()
    if not (casa and mazda):
        return "mantenimiento: sin cosas a las que asociarlo"

    plomero, _ = Party.objects.get_or_create(
        household=household, name="Plomería Hernández",
        defaults={"kind": Party.Kind.ORGANIZATION})
    taller, _ = Party.objects.get_or_create(
        household=household, name="Taller Automotriz del Valle",
        defaults={"kind": Party.Kind.ORGANIZATION})

    planes = [
        (casa, "Revisión del boiler", 12, hoy - dt.timedelta(days=400), 900, plomero),
        (casa, "Impermeabilización", 36, hoy - dt.timedelta(days=500), 18000, None),
        (mazda, "Afinación mayor", 12, hoy - dt.timedelta(days=200), 4750, taller),
    ]
    for cosa, titulo, meses, ultima, coste, proveedor in planes:
        concreto = cosa.as_concrete()
        MaintenancePlan.objects.get_or_create(
            household=household, title=titulo,
            subject_type=ContentType.objects.get_for_model(concreto.__class__),
            subject_id=concreto.pk,
            defaults=dict(basis=MaintenancePlan.Basis.TIME, every_months=meses,
                          last_done_on=ultima, estimated_cost=coste,
                          preferred_provider=proveedor),
        )

    trabajos = [
        (casa, "Cambio de resistencia del boiler", hoy - dt.timedelta(days=400),
         plomero, 1250),
        (mazda, "Afinación y cambio de aceite", hoy - dt.timedelta(days=200),
         taller, 4750),
        (mazda, "Balanceo y alineación", hoy - dt.timedelta(days=45), taller, 890),
    ]
    for cosa, titulo, cuando, proveedor, coste in trabajos:
        concreto = cosa.as_concrete()
        WorkOrder.objects.get_or_create(
            household=household, title=titulo, done_on=cuando,
            subject_type=ContentType.objects.get_for_model(concreto.__class__),
            subject_id=concreto.pk,
            defaults=dict(provider=proveedor, cost=coste, currency="MXN"),
        )

    return (f"mantenimiento: {MaintenancePlan.objects.count()} planes, "
            f"{WorkOrder.objects.count()} trabajos")
