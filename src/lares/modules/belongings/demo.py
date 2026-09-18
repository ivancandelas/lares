"""Objetos de ejemplo: los cuatro casos que justifican el modulo."""

import datetime as dt

from lares.core.models import Location, Party

from .models import Belonging


def seed(household) -> str:
    owner = Party.objects.filter(household=household, is_self=True).first()
    casa, _ = Location.objects.get_or_create(household=household, name="Casa")
    hoy = dt.date.today()

    ejemplos = [
        # Entra por la garantía y la factura.
        dict(name="Refrigerador Samsung", category=Belonging.Category.APPLIANCE,
             brand="Samsung", model_name="RF27T5201", serial_number="0KJ4N92847",
             acquired_on=hoy - dt.timedelta(days=300), purchase_amount=28900,
             current_value=22000, warranty_until=hoy + dt.timedelta(days=65),
             warranty_note="Compresor 10 años, resto 1 año"),
        # Entra por la reventa y el robo.
        dict(name="Bicicleta Trek Marlin 7", category=Belonging.Category.SPORTS,
             brand="Trek", serial_number="WTU241K0392L",
             acquired_on=hoy - dt.timedelta(days=700), purchase_amount=19500,
             current_value=12000),
        # Entra por el seguro.
        dict(name="Anillo de oro 18k", category=Belonging.Category.JEWELRY,
             acquired_on=dt.date(2018, 6, 2), purchase_amount=24000,
             appraised_value=41000, appraised_on=hoy - dt.timedelta(days=420)),
        # Entra por las cuatro.
        dict(name="Guitarra Martin D-28", category=Belonging.Category.INSTRUMENT,
             brand="Martin", model_name="D-28", serial_number="2412887",
             acquired_on=dt.date(2019, 3, 11), purchase_amount=48000,
             current_value=52000, appraised_value=52000),
    ]
    for datos in ejemplos:
        Belonging.objects.get_or_create(
            household=household, name=datos["name"],
            defaults={"kind": "belonging", "owner": owner, "location": casa,
                      "currency": household.currency, **datos},
        )
    return f"objetos: {Belonging.objects.count()}"
