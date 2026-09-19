"""Lo que te cobra cada suscripción contratada."""

import datetime as dt

from django.urls import reverse

from lares.core.registry import Recurring

from .models import Subscription


def recurring(household) -> list:
    hoy = dt.date.today()
    salida = []
    for sub in Subscription.objects.filter(status=Subscription.Status.ACTIVE):
        proximo = None
        if sub.charge_day:
            import calendar

            dia = min(sub.charge_day, calendar.monthrange(hoy.year, hoy.month)[1])
            proximo = dt.date(hoy.year, hoy.month, dia)
            if proximo < hoy:
                mes = hoy.month % 12 + 1
                ano = hoy.year + (1 if mes == 1 else 0)
                proximo = dt.date(ano, mes,
                                  min(sub.charge_day,
                                      calendar.monthrange(ano, mes)[1]))
        nota = sub.get_service_kind_display()
        if sub.access == Subscription.Access.THEIRS:
            nota += ", la pagas tú pero no es tuya"
        salida.append(Recurring(
            title=sub.name,
            amount=sub.amount,
            cycle=sub.cycle,
            currency=sub.currency,
            counterparty=sub.provider,
            next_on=proximo,
            url=reverse("core:resource-detail", args=[sub.pk]),
            source="subscriptions",
            note=nota,
        ))
    return salida
