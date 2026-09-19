"""Lo que debes de tarjetas y de lo que compraste a meses.

Las dos cosas ya viven donde ocurren: el saldo sale del libro y las
mensualidades de la compra que las genero. Aqui solo se dicen.
"""

import datetime as dt

from django.urls import reverse

from lares.core.registry import Owed

from .models import CreditCard
from .models_installment import InstallmentPlan


def owed(household) -> list:
    hoy = dt.date.today()
    salida = []

    for tarjeta in CreditCard.objects.filter(status=CreditCard.Status.ACTIVE):
        saldo = tarjeta.account.balance if tarjeta.account else 0
        if saldo <= 0:
            continue
        vence = None
        if tarjeta.due_day:
            import calendar

            dia = min(tarjeta.due_day, calendar.monthrange(hoy.year, hoy.month)[1])
            vence = dt.date(hoy.year, hoy.month, dia)
            if vence < hoy:
                mes = hoy.month % 12 + 1
                ano = hoy.year + (1 if mes == 1 else 0)
                vence = dt.date(ano, mes,
                                min(tarjeta.due_day, calendar.monthrange(ano, mes)[1]))
        salida.append(Owed(
            direction="out",
            title=tarjeta.name,
            amount=saldo,
            currency=tarjeta.currency,
            counterparty=tarjeta.issuer,
            due_on=vence,
            url=reverse("core:resource-detail", args=[tarjeta.pk]),
            source="finance",
            note="saldo de la tarjeta",
        ))

    # Solo la parte que AUN no te han cargado. Lo ya cobrado vive dentro del
    # saldo de la tarjeta, y sumarlo otra vez duplicaria la misma deuda.
    for plan in InstallmentPlan.objects.select_related("card"):
        diferido = plan.deferred_at(hoy)
        if diferido <= 0:
            continue
        faltan = plan.months - plan.charged_by(hoy)
        salida.append(Owed(
            direction="out",
            title=plan.description,
            amount=diferido,
            currency=plan.card.currency,
            counterparty=plan.merchant,
            url=reverse("core:resource-detail", args=[plan.card_id]),
            source="finance",
            note=f"{faltan} de {plan.months} mensualidades, aún sin cargar",
        ))
    return salida
