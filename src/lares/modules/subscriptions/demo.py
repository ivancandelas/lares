"""Ejemplos de los tres casos que justifican el modulo."""

import datetime as dt

from lares.core.models import Account, Party

from .models import Subscription


def seed(household) -> str:
    owner = Party.objects.filter(household=household, is_self=True).first()
    hijo = Party.objects.filter(household=household, name="Diego").first()
    tarjeta = Account.objects.filter(household=household,
                                     type=Account.Type.LIABILITY).first()
    hoy = dt.date.today()

    def parte(nombre):
        p, _ = Party.objects.get_or_create(
            household=household, name=nombre,
            defaults={"kind": Party.Kind.ORGANIZATION})
        return p

    ejemplos = [
        # Tuya y de las que suben de precio sin avisar.
        dict(name="Netflix", service_kind=Subscription.Kind.STREAMING,
             provider=parte("Netflix"), plan="Estándar con anuncios",
             amount=219, cycle=Subscription.Cycle.MONTHLY, charge_day=14,
             access=Subscription.Access.MINE, started_on=dt.date(2021, 2, 3),
             previous_amount=199, price_changed_on=hoy - dt.timedelta(days=95),
             cancel_url="https://www.netflix.com/cancelplan"),
        dict(name="Disney+", service_kind=Subscription.Kind.STREAMING,
             provider=parte("Disney"), plan="Estándar",
             amount=189, cycle=Subscription.Cycle.MONTHLY, charge_day=22,
             access=Subscription.Access.SHARED, owner=owner),
        # Un VPS: se paga al año y se olvida once meses.
        dict(name="VPS de Hetzner", service_kind=Subscription.Kind.HOSTING,
             provider=parte("Hetzner"), plan="CX22",
             amount=1180, cycle=Subscription.Cycle.YEARLY, charge_day=8,
             access=Subscription.Access.MINE),
        # La cuenta no es tuya, el cargo sí.
        dict(name="iCloud de Diego", service_kind=Subscription.Kind.CLOUD,
             provider=parte("Apple"), plan="200 GB",
             amount=49, cycle=Subscription.Cycle.MONTHLY, charge_day=3,
             access=Subscription.Access.THEIRS, account_holder=hijo, owner=hijo),
        dict(name="Gimnasio", service_kind=Subscription.Kind.GYM,
             provider=parte("Sports World"), amount=899,
             cycle=Subscription.Cycle.MONTHLY, charge_day=1,
             access=Subscription.Access.MINE,
             commitment_until=hoy + dt.timedelta(days=70)),
    ]
    for datos in ejemplos:
        Subscription.objects.get_or_create(
            household=household, name=datos["name"],
            defaults={"kind": "subscription", "currency": household.currency,
                      "paid_with": tarjeta, **datos},
        )

    total = sum(s.yearly_cost or 0 for s in Subscription.objects.all())
    return f"suscripciones: {Subscription.objects.count()} ({total:,.0f} al año)"
