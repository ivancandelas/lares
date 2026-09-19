"""Tres metas: una que llega, una que llega tarde y una deuda que baja."""

import datetime as dt
from decimal import Decimal

from lares.core.models import Account

from .models import Goal, GoalContribution


def seed(household) -> str:
    hoy = dt.date.today()
    nomina = Account.objects.filter(household=household,
                                    name="Cuenta de nómina").first()
    tarjeta = Account.objects.filter(household=household,
                                     name="Tarjeta BBVA").first()

    def meta(nombre, **kwargs):
        datos = dict(currency="MXN", started_on=hoy - dt.timedelta(days=550))
        datos.update(kwargs)
        return Goal.objects.get_or_create(household=household, name=nombre,
                                          defaults=datos)

    # 1. Va tarde: es la que hace falta ver.
    enganche, creada = meta(
        "Enganche de la casa", kind=Goal.Kind.SAVE,
        target_amount=Decimal("1000000"), target_on=dt.date(hoy.year + 2, 4, 1),
        account=nomina, baseline_amount=Decimal("300000"),
    )
    if creada:
        _aportar(household, enganche, 18, Decimal("8500"))

    # 2. Llega holgada.
    viaje, creada = meta(
        "Viaje a Japón", kind=Goal.Kind.SAVE, target_amount=Decimal("120000"),
        target_on=dt.date(hoy.year + 1, 7, 1), account=nomina,
        started_on=hoy - dt.timedelta(days=250),
    )
    if creada:
        _aportar(household, viaje, 8, Decimal("9000"))

    # 3. Una deuda: se mide por el saldo, no por lo que abonaste.
    if tarjeta:
        meta("Quedar libre de la tarjeta", kind=Goal.Kind.PAYOFF,
             target_amount=Decimal("0"), account=tarjeta,
             baseline_amount=Decimal("48000"),
             target_on=dt.date(hoy.year + 1, 1, 1),
             started_on=hoy - dt.timedelta(days=300))

    return f"metas: {Goal.objects.count()}"


def _aportar(household, meta, cuantas: int, importe: Decimal):
    for i in range(cuantas):
        mes = meta.started_on.month - 1 + i
        ano, mes = meta.started_on.year + mes // 12, mes % 12 + 1
        GoalContribution.objects.create(
            household=household, goal=meta, date=dt.date(ano, mes, 5),
            amount=importe,
        )
