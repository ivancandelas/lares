"""La cuota de un préstamo vivo.

Solo la de los que pagas tu: cobrar una cuota es un ingreso, no un gasto que
haya que sumar a lo que te cuesta el mes.
"""

import datetime as dt

from django.urls import reverse

from lares.core.registry import Recurring

from .models import Loan


def recurring(household) -> list:
    hoy = dt.date.today()
    salida = []
    for prestamo in Loan.objects.filter(status=Loan.Status.ACTIVE):
        if (prestamo.is_mine_to_collect or prestamo.is_settled
                or not prestamo.payment_amount):
            continue
        proximo = None
        if prestamo.payment_day:
            import calendar

            dia = min(prestamo.payment_day,
                      calendar.monthrange(hoy.year, hoy.month)[1])
            proximo = dt.date(hoy.year, hoy.month, dia)
            if proximo < hoy:
                mes = hoy.month % 12 + 1
                ano = hoy.year + (1 if mes == 1 else 0)
                proximo = dt.date(ano, mes,
                                  min(prestamo.payment_day,
                                      calendar.monthrange(ano, mes)[1]))
        salida.append(Recurring(
            title=prestamo.name,
            amount=prestamo.payment_amount,
            cycle="monthly",
            currency=prestamo.currency,
            counterparty=prestamo.counterpart,
            next_on=proximo,
            url=reverse("core:resource-detail", args=[prestamo.pk]),
            source="loans",
            note="cuota del préstamo",
        ))
    return salida
