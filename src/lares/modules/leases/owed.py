"""Los meses de renta que no se han saldado, en los dos sentidos."""

from django.urls import reverse

from lares.core.registry import Owed

from .models import Lease


def owed(household) -> list:
    salida = []
    for contrato in Lease.objects.filter(status=Lease.Status.ACTIVE):
        atrasados = contrato.overdue_payments
        if not atrasados:
            continue
        pendiente = sum(p.shortfall for p in atrasados)
        viejo = min(p.due_on for p in atrasados)
        salida.append(Owed(
            direction="in" if contrato.is_landlord else "out",
            title=f"Renta de {contrato.property_ref.name}",
            amount=pendiente,
            currency=contrato.currency,
            counterparty=contrato.counterpart,
            due_on=viejo,
            url=reverse("leases:detail", args=[contrato.pk]),
            source="leases",
            note=f"{len(atrasados)} mes{'es' if len(atrasados) > 1 else ''}",
        ))
    return salida
