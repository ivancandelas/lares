"""Patrimonio neto y salud financiera.

Lo difícil aquí no es sumar: es no contar nada dos veces. Una tarjeta ya es una
cuenta de pasivo; un préstamo que te dieron no es un bien tuyo pero su saldo sí
es deuda; uno que diste es un bien y ya cuenta como recurso.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Posting
from lares.modules.finance import services
from lares.modules.finance.models import CreditCard
from lares.modules.loans.models import Loan, LoanPayment
from lares.modules.vehicles.models import Vehicle

HOY = dt.date.today()


def _mover(household, destino, origen, importe, dias=1):
    entry = Entry.objects.create(household=household,
                                 date=HOY - dt.timedelta(days=dias),
                                 description="Movimiento")
    Posting.objects.create(household=household, entry=entry, account=destino,
                           amount=importe)
    Posting.objects.create(household=household, entry=entry, account=origen,
                           amount=-importe)


@pytest.fixture
def base(scoped, me):
    banco = Account.objects.create(household=scoped, name="Nómina",
                                   type=Account.Type.ASSET)
    sueldo = Account.objects.create(household=scoped, name="Sueldo",
                                    type=Account.Type.INCOME)
    _mover(scoped, banco, sueldo, Decimal("50000"))
    Vehicle.objects.create(household=scoped, name="Mazda", kind="vehicle",
                           owner=me, current_value=Decimal("410000"))
    return {"banco": banco, "sueldo": sueldo}


# --- No contar dos veces ----------------------------------------------------


@pytest.mark.django_db
def test_suma_bienes_y_cuentas(scoped, base):
    n = services.net_worth(scoped)
    assert n["goods"] == Decimal("410000")
    assert n["in_accounts"] == Decimal("50000")
    assert n["net"] == Decimal("460000")


@pytest.mark.django_db
def test_una_tarjeta_cuenta_una_sola_vez(scoped, base, me):
    """Ya es una cuenta de pasivo: sumarla además como cosa la duplicaría."""
    cuenta = Account.objects.create(household=scoped, name="Tarjeta",
                                    type=Account.Type.LIABILITY)
    CreditCard.objects.create(household=scoped, name="Tarjeta", kind="credit_card",
                              account=cuenta, owner=me, cut_day=17, due_day=5)
    gasto = Account.objects.create(household=scoped, name="Compras",
                                   type=Account.Type.EXPENSE)
    _mover(scoped, gasto, cuenta, Decimal("8000"))

    n = services.net_worth(scoped)
    assert n["account_debt"] == Decimal("8000")
    assert n["loan_debt"] == Decimal(0)
    assert n["net"] == Decimal("452000")


@pytest.mark.django_db
def test_un_prestamo_recibido_es_deuda_pero_no_un_bien(scoped, base, me):
    Loan.objects.create(household=scoped, name="Hipoteca", kind="loan",
                        direction=Loan.Direction.BORROWED,
                        principal=Decimal("1700000"), owner=me)

    n = services.net_worth(scoped)
    assert n["loan_debt"] == Decimal("1700000")
    assert n["goods"] == Decimal("410000")      # el préstamo no suma como bien
    assert n["net"] == Decimal("-1240000")


@pytest.mark.django_db
def test_un_prestamo_concedido_es_un_bien_y_no_deuda(scoped, base, me):
    Loan.objects.create(household=scoped, name="A mi hermano", kind="loan",
                        direction=Loan.Direction.LENT,
                        principal=Decimal("60000"), owner=me)

    n = services.net_worth(scoped)
    assert n["loan_debt"] == Decimal(0)
    assert n["goods"] == Decimal("470000")      # 410.000 + los 60.000 que te deben
    assert n["net"] == Decimal("520000")


@pytest.mark.django_db
def test_abonar_un_prestamo_baja_la_deuda(scoped, base, me):
    prestamo = Loan.objects.create(
        household=scoped, name="Hipoteca", kind="loan",
        direction=Loan.Direction.BORROWED, principal=Decimal("100000"), owner=me,
    )
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("30000"))

    assert services.net_worth(scoped)["loan_debt"] == Decimal("70000")


@pytest.mark.django_db
def test_lo_dado_de_baja_no_cuenta(scoped, base, me):
    coche = Vehicle.objects.get(name="Mazda")
    coche.dispose(Vehicle.Disposal.SOLD, amount=Decimal("390000"))

    assert services.net_worth(scoped)["goods"] == Decimal(0)


# --- La hipoteca colgada del inmueble ---------------------------------------


@pytest.mark.django_db
def test_un_prestamo_se_puede_atar_a_la_cosa_que_garantiza(scoped, base, me):
    from lares.modules.loans.forms import LoanForm, loans_against, secured_resource

    coche = Vehicle.objects.get(name="Mazda")
    form = LoanForm({
        "name": "Crédito del coche", "direction": "borrowed",
        "principal": "300000", "interest_kind": "none", "state": "current",
        "status": "active", "secured_by": coche.pk,
    }, household=scoped)
    assert form.is_valid(), form.errors
    prestamo = form.save()

    assert secured_resource(prestamo).pk == coche.pk
    assert [x.pk for x in loans_against(coche)] == [prestamo.pk]


@pytest.mark.django_db
def test_la_ficha_dice_cuanto_de_esa_cosa_es_tuyo(scoped, base, me):
    from django.contrib.contenttypes.models import ContentType

    from lares.core.models import Link
    from lares.modules.loans.apps import _deuda_de

    coche = Vehicle.objects.get(name="Mazda")
    prestamo = Loan.objects.create(
        household=scoped, name="Crédito", kind="loan",
        direction=Loan.Direction.BORROWED, principal=Decimal("300000"), owner=me,
    )
    Link.objects.create(
        household=scoped, role="secures",
        source_type=ContentType.objects.get_for_model(Loan), source_id=prestamo.pk,
        target_type=ContentType.objects.get_for_model(Vehicle), target_id=coche.pk,
    )
    datos = _deuda_de(coche)

    assert datos["valor"] == Decimal("410000")
    assert datos["total"] == Decimal("300000")
    assert datos["equity"] == Decimal("110000")


# --- Salud financiera -------------------------------------------------------


@pytest.mark.django_db
def test_el_colchon_mide_cuantos_meses_aguantas(scoped, base):
    gasto = Account.objects.create(household=scoped, name="Gastos",
                                   type=Account.Type.EXPENSE)
    for dias in (10, 40, 70):
        _mover(scoped, gasto, base["banco"], Decimal("10000"), dias=dias)

    s = services.health(scoped)
    assert s["monthly_spend"] == Decimal("10000")
    # Quedan 20.000 en el banco: dos meses.
    assert s["runway"] == pytest.approx(2.0, abs=0.01)


@pytest.mark.django_db
def test_lo_comprometido_incluye_suscripciones_y_cuotas(scoped, base, me):
    from lares.modules.subscriptions.models import Subscription

    Subscription.objects.create(household=scoped, name="Netflix", kind="subscription",
                                amount=Decimal("219"),
                                cycle=Subscription.Cycle.MONTHLY, charge_day=14)
    Loan.objects.create(household=scoped, name="Hipoteca", kind="loan",
                        direction=Loan.Direction.BORROWED,
                        principal=Decimal("1700000"),
                        payment_amount=Decimal("17180"), payment_day=5, owner=me)

    assert services.health(scoped)["fixed_monthly"] == Decimal("17399.00")


@pytest.mark.django_db
def test_lo_que_tu_prestaste_no_cuenta_como_cuota_tuya(scoped, base, me):
    Loan.objects.create(household=scoped, name="A mi hermano", kind="loan",
                        direction=Loan.Direction.LENT, principal=Decimal("60000"),
                        payment_amount=Decimal("5000"), payment_day=15, owner=me)

    assert services.health(scoped)["fixed_monthly"] == Decimal(0)


@pytest.mark.django_db
def test_sin_ingresos_los_indicadores_no_mienten(scoped, me):
    """Mejor un «—» que un número inventado."""
    s = services.health(scoped)
    assert s["savings_rate"] is None
    assert s["debt_to_income"] is None
    assert s["fixed_share"] is None
