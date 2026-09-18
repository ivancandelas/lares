"""Datos de ejemplo del modulo de dinero.

Incluye movimientos reales -en partida doble- porque un saldo inventado no
demostraria nada: el punto es que el saldo se calcula desde los apuntes.
"""

import datetime as dt

from lares.core.models import Account, Entry, Party, Posting

from .models import CreditCard


def seed(household) -> str:
    banco, _ = Party.objects.get_or_create(
        household=household, name="BBVA", defaults={"kind": Party.Kind.ORGANIZATION}
    )

    nomina, _ = Account.objects.get_or_create(
        household=household, name="Cuenta de nómina", type=Account.Type.ASSET,
        defaults={"institution": banco, "last_four": "4417", "currency": "MXN"},
    )
    tdc_account, _ = Account.objects.get_or_create(
        household=household, name="Tarjeta BBVA", type=Account.Type.LIABILITY,
        defaults={"institution": banco, "last_four": "1234", "currency": "MXN"},
    )
    gasto_auto, _ = Account.objects.get_or_create(
        household=household, name="Gastos: vehículo", type=Account.Type.EXPENSE,
    )
    gasto_super, _ = Account.objects.get_or_create(
        household=household, name="Gastos: supermercado", type=Account.Type.EXPENSE,
    )
    sueldo, _ = Account.objects.get_or_create(
        household=household, name="Sueldo", type=Account.Type.INCOME,
    )

    card, _ = CreditCard.objects.get_or_create(
        household=household, name="Tarjeta BBVA",
        defaults=dict(
            kind="credit_card", issuer=banco, account=tdc_account, last_four="1234",
            credit_limit=60000, cut_day=17, due_day=5, apr=42.5, currency="MXN",
        ),
    )

    hoy = dt.date.today()
    movimientos = [
        # El sueldo entra en la cuenta: sin ingreso, el saldo no significa nada.
        ("Nómina de septiembre", nomina, sueldo, 42000, 3),
        ("Gasolina", gasto_auto, tdc_account, 980, 6),
        ("Supermercado", gasto_super, tdc_account, 2340, 4),
        ("Servicio de agencia", gasto_auto, tdc_account, 4750, 12),
    ]
    for concepto, gasto, origen, importe, hace_dias in movimientos:
        entry, creado = Entry.objects.get_or_create(
            household=household, description=concepto,
            date=hoy - dt.timedelta(days=hace_dias),
            defaults={"source": "demo"},
        )
        if not creado:
            continue
        # Partida doble: el gasto carga, la tarjeta abona. Suman cero.
        Posting.objects.create(household=household, entry=entry, account=gasto,
                               amount=importe, currency="MXN")
        Posting.objects.create(household=household, entry=entry, account=origen,
                               amount=-importe, currency="MXN")

    return f"cuentas: {Account.objects.count()}, tarjetas: {CreditCard.objects.count()}, " \
           f"saldo tarjeta: {tdc_account.balance:,.0f} MXN (nómina: {nomina.name})"
