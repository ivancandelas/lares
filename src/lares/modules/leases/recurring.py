"""La renta: el recurrente más grande de casi cualquier casa."""

import datetime as dt

from django.urls import reverse

from lares.core.registry import Recurring

from .models import Lease


def recurring(household) -> list:
    hoy = dt.date.today()
    salida = []
    for contrato in Lease.objects.filter(status=Lease.Status.ACTIVE):
        if not (contrato.is_live and not contrato.is_landlord):
            continue        # lo que cobras no es un gasto recurrente tuyo
        import calendar

        dia = min(contrato.rent_day, calendar.monthrange(hoy.year, hoy.month)[1])
        proximo = dt.date(hoy.year, hoy.month, dia)
        if proximo < hoy:
            mes = hoy.month % 12 + 1
            ano = hoy.year + (1 if mes == 1 else 0)
            proximo = dt.date(ano, mes,
                              min(contrato.rent_day,
                                  calendar.monthrange(ano, mes)[1]))
        salida.append(Recurring(
            title=f"Renta de {contrato.property_ref.name}",
            amount=contrato.rent_amount,
            cycle="monthly",
            currency=contrato.currency,
            counterparty=contrato.counterpart,
            next_on=proximo,
            url=reverse("leases:detail", args=[contrato.pk]),
            source="leases",
            note="renta",
        ))
    return salida
