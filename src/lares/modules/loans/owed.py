"""Lo que se debe de un préstamo, en los dos sentidos."""

from django.urls import reverse

from lares.core.registry import Owed

from .models import Loan


def owed(household) -> list:
    salida = []
    for prestamo in Loan.objects.filter(status=Loan.Status.ACTIVE):
        if prestamo.is_settled:
            continue
        salida.append(Owed(
            direction="in" if prestamo.is_mine_to_collect else "out",
            title=prestamo.name,
            amount=prestamo.outstanding,
            currency=prestamo.currency,
            counterparty=prestamo.counterpart,
            url=reverse("core:resource-detail", args=[prestamo.pk]),
            source="loans",
            note=("sin contrato" if prestamo.is_informal else ""),
        ))
    return salida
