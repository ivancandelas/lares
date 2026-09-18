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

    mascotas, _ = Account.objects.get_or_create(
        household=household, name="Gastos: mascotas", type=Account.Type.EXPENSE)
    familia, _ = Account.objects.get_or_create(
        household=household, name="Gastos: familia", type=Account.Type.EXPENSE)

    walmart, _ = Party.objects.get_or_create(
        household=household, name="Walmart", defaults={"kind": Party.Kind.ORGANIZATION})
    pemex, _ = Party.objects.get_or_create(
        household=household, name="Gasolinera Pemex Américas",
        defaults={"kind": Party.Kind.ORGANIZATION})
    veterinaria, _ = Party.objects.get_or_create(
        household=household, name="Veterinaria San Ángel",
        defaults={"kind": Party.Kind.ORGANIZATION})
    hijo, _ = Party.objects.get_or_create(
        household=household, name="Diego", defaults={"kind": Party.Kind.PERSON})
    esposa, _ = Party.objects.get_or_create(
        household=household, name="Mariana", defaults={"kind": Party.Kind.PERSON})

    mazda = None
    from lares.core.models.resource import Resource
    mazda = Resource.objects.filter(household=household, name="Mazda CX-5").first()

    hoy = dt.date.today()
    # (concepto, categoría, origen, importe, hace días, comercio, para quién, sobre qué)
    movimientos = [
        # El sueldo entra en la cuenta: sin ingreso, el saldo no significa nada.
        ("Nómina de septiembre", nomina, sueldo, 42000, 3, None, None, None),
        ("Gasolina", gasto_auto, tdc_account, 980, 6, pemex, None, mazda),
        ("Gasolina", gasto_auto, tdc_account, 1050, 34, pemex, None, mazda),
        ("Despensa de la semana", gasto_super, tdc_account, 2340, 4, walmart, None, None),
        ("Despensa de la semana", gasto_super, tdc_account, 1980, 11, walmart, None, None),
        ("Despensa y limpieza", gasto_super, tdc_account, 2610, 25, walmart, None, None),
        ("Servicio de agencia", gasto_auto, tdc_account, 4750, 12, None, None, mazda),
        ("Croquetas y vacuna", mascotas, tdc_account, 1420, 9, veterinaria, None, None),
        ("Baño y desparasitante", mascotas, tdc_account, 680, 40, veterinaria, None, None),
        ("Mesada de Diego", familia, nomina, 1500, 2, None, hijo, None),
        ("Mesada de Diego", familia, nomina, 1500, 32, None, hijo, None),
        ("Zapatos para Diego", familia, tdc_account, 1890, 20, walmart, hijo, None),
        ("Gasto de Mariana", familia, nomina, 4000, 5, None, esposa, None),
    ]
    for concepto, gasto, origen, importe, hace_dias, comercio, para, sobre in movimientos:
        fecha = hoy - dt.timedelta(days=hace_dias)
        entry, creado = Entry.objects.get_or_create(
            household=household, description=concepto, date=fecha,
            defaults={"source": "demo", "counterparty": comercio},
        )
        if not creado:
            continue
        # Partida doble: el gasto carga, la cuenta abona. Suman cero.
        Posting.objects.create(household=household, entry=entry, account=gasto,
                               amount=importe, currency="MXN",
                               beneficiary=para, dimension=sobre)
        Posting.objects.create(household=household, entry=entry, account=origen,
                               amount=-importe, currency="MXN")

    _seed_budgets(household, {"super": gasto_super, "auto": gasto_auto,
                              "mascotas": mascotas, "familia": familia})

    return f"cuentas: {Account.objects.count()}, tarjetas: {CreditCard.objects.count()}, " \
           f"saldo tarjeta: {tdc_account.balance:,.0f} MXN (nómina: {nomina.name})"


def _seed_budgets(household, cuentas):
    """Topes de ejemplo, uno de ellos ya pasado de ritmo."""
    from .models_budget import Budget

    topes = [(cuentas["super"], 8000), (cuentas["auto"], 5000),
             (cuentas["mascotas"], 1500), (cuentas["familia"], 9000)]
    for cuenta, importe in topes:
        Budget.objects.get_or_create(
            household=household, account=cuenta, defaults={"amount": importe}
        )
