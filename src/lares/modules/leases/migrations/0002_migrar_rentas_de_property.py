"""Los datos de renta que vivian sueltos en Property pasan al contrato.

Tener los dos sitios seria dos fuentes de verdad: al primer cambio, nadie
sabria cual de las dos cifras es la buena.
"""

from django.db import migrations


def a_contratos(apps, schema_editor):
    import datetime as dt

    Property = apps.get_model("property", "Property")
    Lease = apps.get_model("leases", "Lease")

    for prop in Property.objects.filter(tenure="rented").exclude(rent_amount=None):
        if Lease.objects.filter(property_ref_id=prop.pk).exists():
            continue

        # Se crea la hija y Django inserta la fila padre: hacerlo a mano deja
        # el padre sin los campos heredados y la fila sale vacia.
        Lease.objects.create(
            household_id=prop.household_id,
            kind="lease",
            name=f"Renta de {prop.name}",
            status="active",
            currency=prop.currency or "",
            owner_id=prop.owner_id,
            extra={},
            direction="tenant",
            property_ref_id=prop.pk,
            counterpart_id=prop.landlord_id,
            starts_on=prop.acquired_on or dt.date.today(),
            ends_on=prop.lease_ends_on,
            rent_amount=prop.rent_amount,
            rent_day=prop.rent_due_day or 1,
            deposit_amount=prop.deposit_amount,
            increase_kind="none",
        )


def atras(apps, schema_editor):
    """Devuelve los datos a Property antes de borrar los contratos."""
    Lease = apps.get_model("leases", "Lease")
    Property = apps.get_model("property", "Property")

    for lease in Lease.objects.filter(direction="tenant"):
        Property.objects.filter(pk=lease.property_ref_id).update(
            rent_amount=lease.rent_amount,
            rent_due_day=lease.rent_day,
            deposit_amount=lease.deposit_amount,
            lease_ends_on=lease.ends_on,
            landlord_id=lease.counterpart_id,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("leases", "0001_initial"),
        ("property", "0001_initial"),
    ]

    operations = [migrations.RunPython(a_contratos, atras)]
