"""La renta: el recurrente más grande de casi cualquier casa.

Va en los dos sentidos. La que pagas se va cada mes; la que cobras entra cada
mes, y dejarla fuera haria que "lo que queda al mes" saliera mucho mas bajo de
lo que es para quien vive de rentar.
"""

import datetime as dt

from django.urls import reverse

from lares.core.registry import Recurring

from .models import Lease


def recurring(household) -> list:
    hoy = dt.date.today()
    salida = []
    for contrato in Lease.objects.filter(status=Lease.Status.ACTIVE):
        if not contrato.is_live:
            continue
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
            direction="in" if contrato.is_landlord else "out",
            currency=contrato.currency,
            counterparty=contrato.counterpart,
            next_on=proximo,
            url=reverse("leases:detail", args=[contrato.pk]),
            source="leases",
            note="renta que cobras" if contrato.is_landlord
                 else "renta que pagas",
        ))
    return salida
