"""Datos de ejemplo del modulo de vehiculos."""

import datetime as dt

from lares.core.models import Location, Party

from .models import Vehicle


def seed(household) -> str:
    owner = Party.objects.filter(household=household, is_self=True).first()
    garage = Location.objects.filter(household=household, name="Cochera").first()

    Vehicle.objects.get_or_create(
        household=household, name="Mazda CX-5",
        defaults=dict(
            kind="vehicle", make="Mazda", model="CX-5", year=2022,
            plates="JGT1234", vin="JM3KFBDM1N0123456",
            odometer_km=38400, avg_km_per_month=900,
            service_interval_km=10000, last_service_km=30000,
            owner=owner, location=garage,
            acquired_on=dt.date(2022, 4, 12),
            purchase_amount=520000, current_value=410000, currency="MXN",
        ),
    )
    Vehicle.objects.get_or_create(
        household=household, name="Nissan Versa",
        defaults=dict(
            kind="vehicle", make="Nissan", model="Versa", year=2019,
            plates="JHK9876", odometer_km=91200, avg_km_per_month=600,
            service_interval_km=10000, last_service_km=90000, owner=owner,
        ),
    )
    return f"vehiculos: {Vehicle.objects.count()}"
