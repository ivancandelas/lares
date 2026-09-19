"""Lo que se cobra y lo que entra cada tanto, según el módulo de dinero."""

import datetime as dt

from django.urls import reverse

from lares.core.registry import Recurring

from .models_income import RecurringIncome


def recurring(household) -> list:
    hoy = dt.date.today()
    return [
        Recurring(
            title=ingreso.name,
            amount=ingreso.amount,
            cycle=ingreso.cycle,
            direction="in",
            pk=None,
            currency=ingreso.currency,
            counterparty=ingreso.payer,
            next_on=ingreso.next_on(hoy),
            url=reverse("finance:income-edit", args=[ingreso.pk]),
            source="finance_income",
            note=ingreso.note or "ingreso",
        )
        for ingreso in RecurringIncome.objects.filter(is_active=True)
        if ingreso.is_live
    ]
