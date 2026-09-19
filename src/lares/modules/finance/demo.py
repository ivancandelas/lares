"""Datos de ejemplo del modulo de dinero.

Incluye movimientos reales -en partida doble- porque un saldo inventado no
demostraria nada: el punto es que el saldo se calcula desde los apuntes.
"""

import datetime as dt
from decimal import Decimal

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

    # El efectivo es una cuenta de activo como cualquier otra. Tenerlo aparte
    # es lo que permite que sacar del cajero sea un traspaso y no un gasto.
    efectivo, _ = Account.objects.get_or_create(
        household=household, name="Efectivo", type=Account.Type.ASSET,
        defaults={"currency": "MXN"},
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

    _seed_cash(household, nomina, efectivo, gasto_super)
    _seed_income(household, nomina, sueldo, banco)
    _seed_plan(household, {"super": gasto_super, "auto": gasto_auto,
                           "mascotas": mascotas, "familia": familia})
    _obra(household)

    return f"cuentas: {Account.objects.count()}, tarjetas: {CreditCard.objects.count()}, " \
           f"saldo tarjeta: {tdc_account.balance:,.0f} MXN (nómina: {nomina.name})"



def _seed_plan(household, cuentas):
    """Un presupuesto del año con una categoría que se va a pasar.

    El vehiculo va deliberadamente corto: sin una linea desviada no se ve lo
    unico que distingue un presupuesto de una tabla, que es la proyeccion.
    """
    from .models_plan import Plan, PlanLine

    hoy = dt.date.today()
    plan, creado = Plan.objects.get_or_create(
        household=household, name=f"Presupuesto {hoy.year}",
        defaults=dict(kind=Plan.Kind.ANNUAL, year=hoy.year, currency="MXN",
                      note="Partido de lo del año pasado y ajustado."),
    )
    if not creado:
        return

    # Unas al mes y otras de golpe: es lo que distingue el super del
    # mantenimiento del coche, y forzar una sola cadencia estropea la mitad.
    previsto = [
        (cuentas["super"], 8000, PlanLine.Cadence.MONTHLY),
        (cuentas["familia"], 9000, PlanLine.Cadence.MONTHLY),
        (cuentas["mascotas"], 1500, PlanLine.Cadence.MONTHLY),
        (cuentas["auto"], 24000, PlanLine.Cadence.TOTAL),
    ]
    for cuenta, importe, cadencia in previsto:
        PlanLine.objects.get_or_create(
            household=household, plan=plan, account=cuenta,
            defaults={"amount": Decimal(importe), "cadence": cadencia},
        )


def _obra(household):
    """El presupuesto de un proyecto, que es donde más se desvía."""
    from lares.core.models import Entry, Posting
    from .models_plan import Plan, PlanLine

    hoy = dt.date.today()
    obra, creado = Plan.objects.get_or_create(
        household=household, name="Remodelación de la cocina",
        defaults=dict(kind=Plan.Kind.PROJECT, currency="MXN",
                      starts_on=hoy - dt.timedelta(days=60),
                      ends_on=hoy + dt.timedelta(days=60),
                      note="Presupuesto cerrado con el contratista."),
    )
    if not creado:
        return

    materiales, _ = Account.objects.get_or_create(
        household=household, name="Gastos: obra y materiales",
        defaults={"type": Account.Type.EXPENSE})
    banco = Account.objects.filter(household=household,
                                   type=Account.Type.ASSET).first()
    PlanLine.objects.create(household=household, plan=obra,
                            account=materiales, amount=Decimal("120000"),
                            cadence=PlanLine.Cadence.TOTAL)

    # Gasto atribuido al proyecto con la dimension del libro: sin eso, la obra
    # se comeria todo el gasto de casa del ano.
    for hace, importe, concepto in ((50, 42000, "Anticipo al contratista"),
                                    (20, 38000, "Muebles y cubierta")):
        asiento = Entry.objects.create(
            household=household, date=hoy - dt.timedelta(days=hace),
            description=concepto, source="demo")
        Posting.objects.create(household=household, entry=asiento,
                               account=materiales, amount=Decimal(importe),
                               currency="MXN", dimension=obra)
        if banco:
            Posting.objects.create(household=household, entry=asiento,
                                   account=banco, amount=-Decimal(importe),
                                   currency="MXN")


def _seed_cash(household, nomina, efectivo, categoria):
    """Un retiro del cajero y un gasto pagado en efectivo.

    El retiro es un traspaso, no un gasto: si se anotara como gasto, el dinero
    se contaria dos veces -una al sacarlo y otra al gastarlo-.
    """
    hoy = dt.date.today()
    if Entry.objects.filter(household=household,
                            description="Retiro del cajero").exists():
        return

    retiro = Entry.objects.create(household=household, source="transfer",
                                  date=hoy - dt.timedelta(days=8),
                                  description="Retiro del cajero")
    Posting.objects.create(household=household, entry=retiro, account=nomina,
                           amount=Decimal("-4000"), currency="MXN")
    Posting.objects.create(household=household, entry=retiro, account=efectivo,
                           amount=Decimal("4000"), currency="MXN")

    gasto = Entry.objects.create(household=household, source="demo",
                                 date=hoy - dt.timedelta(days=6),
                                 description="Mercado del domingo")
    Posting.objects.create(household=household, entry=gasto, account=categoria,
                           amount=Decimal("850"), currency="MXN")
    Posting.objects.create(household=household, entry=gasto, account=efectivo,
                           amount=Decimal("-850"), currency="MXN")


def _seed_income(household, nomina, sueldo, banco):
    """El sueldo, declarado. Deja de ser una estimación del flujo."""
    from .models_income import RecurringIncome

    empresa, _ = Party.objects.get_or_create(
        household=household, name="Softtek",
        defaults={"kind": Party.Kind.ORGANIZATION})
    RecurringIncome.objects.get_or_create(
        household=household, name="Nómina",
        defaults=dict(payer=empresa, amount=Decimal("42000"),
                      cycle=RecurringIncome.Cycle.MONTHLY, pay_day=30,
                      account=nomina, category=sueldo, currency="MXN",
                      note="Neto, después de retenciones."),
    )
