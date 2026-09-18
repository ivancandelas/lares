"""Cartera de ejemplo: los cuatro casos que justifican el modulo."""

import datetime as dt

from lares.core.models import Party

from .models import Property, Service


def seed(household) -> str:
    owner = Party.objects.filter(household=household, is_self=True).first()
    hoy = dt.date.today()

    siapa, _ = Party.objects.get_or_create(
        household=household, name="SIAPA", defaults={"kind": Party.Kind.ORGANIZATION})
    cfe, _ = Party.objects.get_or_create(
        household=household, name="CFE", defaults={"kind": Party.Kind.ORGANIZATION})
    casero, _ = Party.objects.get_or_create(
        household=household, name="Sr. Ramírez", defaults={"kind": Party.Kind.PERSON})

    # 1. Donde vives, y no es tuyo: genera gasto, no patrimonio.
    casa_rentada, _ = Property.objects.get_or_create(
        household=household, name="Casa de Providencia",
        defaults=dict(
            kind="property", property_type=Property.Type.HOUSE,
            tenure=Property.Tenure.RENTED, use=Property.Use.LIVED_IN,
            city="Guadalajara", subdivision="MX-JAL", built_m2=180,
            landlord=casero, rent_amount=18500, rent_due_day=5,
            deposit_amount=37000, lease_ends_on=hoy + dt.timedelta(days=100),
            owner=owner, currency="MXN",
        ),
    )
    # 2. Tuyo y rentado a otro: en F5 se le pondrá contrato e inquilino.
    Property.objects.get_or_create(
        household=household, name="Departamento en Chapalita",
        defaults=dict(
            kind="property", property_type=Property.Type.APARTMENT,
            tenure=Property.Tenure.OWNED, use=Property.Use.RENTED_OUT,
            city="Guadalajara", subdivision="MX-JAL", built_m2=78,
            acquired_on=dt.date(2021, 8, 30), purchase_amount=2150000,
            current_value=2900000, cadastral_id="D-4471-22",
            deed_number="45.882", deed_date=dt.date(2021, 8, 30),
            predial_month=1, predial_amount=4800, owner=owner, currency="MXN",
        ),
    )
    # 3. Un terreno: sin construcción, sin servicios, pero con predial.
    Property.objects.get_or_create(
        household=household, name="Terreno en Tapalpa",
        defaults=dict(
            kind="property", property_type=Property.Type.LAND,
            tenure=Property.Tenure.CO_OWNED, use=Property.Use.EMPTY,
            city="Tapalpa", subdivision="MX-JAL", land_m2=1200,
            acquired_on=dt.date(2023, 5, 12), purchase_amount=890000,
            current_value=1150000, ownership_share=50,
            predial_month=2, predial_amount=1350, owner=owner, currency="MXN",
        ),
    )

    for kind, nombre, proveedor, ciclo, dia, importe in [
        (Service.Kind.WATER, "Agua de Providencia", siapa,
         Service.Cycle.BIMONTHLY, 20, 640),
        (Service.Kind.POWER, "Luz de Providencia", cfe,
         Service.Cycle.BIMONTHLY, 12, 1180),
    ]:
        Service.objects.get_or_create(
            household=household, name=nombre,
            defaults=dict(kind="service", service_kind=kind,
                          property_ref=casa_rentada, provider=proveedor,
                          cycle=ciclo, due_day=dia, typical_amount=importe,
                          currency="MXN"),
        )

    return (f"inmuebles: {Property.objects.count()} "
            f"(uno rentado, uno en renta, un terreno), "
            f"servicios: {Service.objects.count()}")
