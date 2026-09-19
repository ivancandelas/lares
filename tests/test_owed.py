"""Quién debe a quién.

La decisión de esta pantalla es que **no guarda nada**. No hay tabla de cuentas
por cobrar ni por pagar: lo que se debe ya vive donde ocurre —el préstamo sabe
cuánto falta, el contrato sabe qué meses no llegaron, la tarjeta sabe su saldo—
y copiarlo a una tabla aparte crearía dos verdades que se separan al primer
abono.

Lo que se prueba, entonces, es que la suma junta lo de todos sin contar nada dos
veces, y que el núcleo sigue sin saber qué módulos existen.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Party, Posting
from lares.core.registry import registry
from lares.modules.finance.models import CreditCard
from lares.modules.finance.models_installment import InstallmentPlan
from lares.modules.leases.models import Lease, RentPayment
from lares.modules.loans.models import Loan
from lares.modules.property.models import Property

HOY = dt.date.today()


def _tarjeta(household, saldo, **kwargs):
    banco = Party.objects.create(household=household, name="BBVA",
                                 kind=Party.Kind.ORGANIZATION)
    cuenta = Account.objects.create(household=household, name="Tarjeta",
                                    type=Account.Type.LIABILITY)
    gasto = Account.objects.create(household=household, name="Compras",
                                   type=Account.Type.EXPENSE)
    entry = Entry.objects.create(household=household, description="Compras",
                                 date=HOY - dt.timedelta(days=20))
    Posting.objects.create(household=household, entry=entry, account=gasto,
                           amount=Decimal(saldo), currency="MXN")
    Posting.objects.create(household=household, entry=entry, account=cuenta,
                           amount=-Decimal(saldo), currency="MXN")
    datos = dict(kind="credit_card", name="Tarjeta BBVA", issuer=banco,
                 account=cuenta, last_four="1234", due_day=5, currency="MXN")
    datos.update(kwargs)
    return CreditCard.objects.create(household=household, **datos)


def _por_titulo(household):
    return {o.title: o for o in registry.owed_all(household)}


# --- Los dos lados ----------------------------------------------------------


@pytest.mark.django_db
def test_lo_prestado_se_cobra_y_lo_recibido_se_paga(scoped):
    Loan.objects.create(household=scoped, kind="loan", name="A mi hermano",
                        direction=Loan.Direction.LENT,
                        principal=Decimal("50000"), currency="MXN")
    Loan.objects.create(household=scoped, kind="loan", name="Del banco",
                        direction=Loan.Direction.BORROWED,
                        principal=Decimal("200000"), currency="MXN")

    partidas = _por_titulo(scoped)
    assert partidas["A mi hermano"].direction == "in"
    assert partidas["Del banco"].direction == "out"


@pytest.mark.django_db
def test_un_prestamo_saldado_desaparece(scoped):
    from lares.modules.loans.models import LoanPayment

    prestamo = Loan.objects.create(
        household=scoped, kind="loan", name="Saldado",
        direction=Loan.Direction.LENT, principal=Decimal("5000"), currency="MXN")
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("5000"))

    assert "Saldado" not in _por_titulo(scoped)


@pytest.mark.django_db
def test_la_renta_sin_cobrar_aparece_como_por_cobrar(scoped):
    inmueble = Property.objects.create(household=scoped, kind="property",
                                       name="Depto", currency="MXN")
    contrato = Lease.objects.create(
        household=scoped, kind="lease", name="Contrato", property_ref=inmueble,
        direction=Lease.Direction.LANDLORD, starts_on=HOY - dt.timedelta(days=90),
        rent_amount=Decimal("14500"), rent_day=5, currency="MXN")
    RentPayment.objects.create(household=scoped, lease=contrato, period="2020-01",
                               due_on=HOY - dt.timedelta(days=10),
                               amount=Decimal("14500"))

    partida = _por_titulo(scoped)["Renta de Depto"]
    assert partida.direction == "in"
    assert partida.amount == 14500
    assert partida.is_overdue


@pytest.mark.django_db
def test_lo_abonado_a_medias_solo_cuenta_por_lo_que_falta(scoped):
    inmueble = Property.objects.create(household=scoped, kind="property",
                                       name="Depto", currency="MXN")
    contrato = Lease.objects.create(
        household=scoped, kind="lease", name="Contrato", property_ref=inmueble,
        direction=Lease.Direction.LANDLORD, starts_on=HOY - dt.timedelta(days=90),
        rent_amount=Decimal("14500"), rent_day=5, currency="MXN")
    RentPayment.objects.create(household=scoped, lease=contrato, period="2020-01",
                               due_on=HOY - dt.timedelta(days=10),
                               amount=Decimal("14500"),
                               paid_on=HOY - dt.timedelta(days=9),
                               amount_paid=Decimal("6000"))

    assert _por_titulo(scoped)["Renta de Depto"].amount == 8500


# --- Nada se cuenta dos veces -----------------------------------------------


@pytest.mark.django_db
def test_de_una_compra_a_meses_solo_cuenta_lo_que_aun_no_te_cargan(scoped):
    """Lo ya cobrado vive dentro del saldo de la tarjeta.

    Sumar la mensualidad completa ademas del saldo contaria la misma deuda dos
    veces, y el total diria que debes mas de lo que debes.
    """
    tarjeta = _tarjeta(scoped, 12000)
    InstallmentPlan.objects.create(
        household=scoped, card=tarjeta, description="Refrigerador",
        total_amount=Decimal("12000"), months=12, interest_free=True,
        first_charge_on=HOY - dt.timedelta(days=150),
    )

    partidas = _por_titulo(scoped)
    # Cinco o seis mensualidades cobradas: solo lo que queda diferido.
    assert partidas["Refrigerador"].amount < 12000
    assert partidas["Tarjeta BBVA"].amount == 12000


@pytest.mark.django_db
def test_una_compra_a_meses_ya_terminada_no_aparece(scoped):
    tarjeta = _tarjeta(scoped, 12000)
    InstallmentPlan.objects.create(
        household=scoped, card=tarjeta, description="Vieja",
        total_amount=Decimal("12000"), months=3, interest_free=True,
        first_charge_on=HOY - dt.timedelta(days=400),
    )

    assert "Vieja" not in _por_titulo(scoped)


@pytest.mark.django_db
def test_una_tarjeta_sin_saldo_no_aparece(scoped):
    _tarjeta(scoped, 0)

    assert "Tarjeta BBVA" not in _por_titulo(scoped)


# --- La pantalla ------------------------------------------------------------


@pytest.mark.django_db
def test_la_pantalla_suma_los_dos_lados(sesion_admin, household):
    Loan.objects.create(household=household, kind="loan", name="A mi hermano",
                        direction=Loan.Direction.LENT,
                        principal=Decimal("50000"), currency="MXN")
    Loan.objects.create(household=household, kind="loan", name="Del banco",
                        direction=Loan.Direction.BORROWED,
                        principal=Decimal("200000"), currency="MXN")

    contexto = sesion_admin.get("/se-debe/").context
    assert contexto["total_cobrar"] == 50000
    assert contexto["total_pagar"] == 200000
    assert contexto["neto"] == -150000


@pytest.mark.django_db
def test_lo_vencido_va_primero(sesion_admin, household):
    inmueble = Property.objects.create(household=household, kind="property",
                                       name="Depto", currency="MXN")
    contrato = Lease.objects.create(
        household=household, kind="lease", name="Contrato",
        property_ref=inmueble, direction=Lease.Direction.LANDLORD,
        starts_on=HOY - dt.timedelta(days=90), rent_amount=Decimal("1000"),
        rent_day=5, currency="MXN")
    RentPayment.objects.create(household=household, lease=contrato,
                               period="2020-01",
                               due_on=HOY - dt.timedelta(days=10),
                               amount=Decimal("1000"))
    Loan.objects.create(household=household, kind="loan", name="Sin fecha",
                        direction=Loan.Direction.LENT,
                        principal=Decimal("99999"), currency="MXN")

    cobrar = sesion_admin.get("/se-debe/").context["cobrar"]
    assert cobrar[0].is_overdue          # aunque sea el importe más pequeño


@pytest.mark.django_db
def test_la_pantalla_abre_sin_nada_registrado(sesion_admin, household):
    respuesta = sesion_admin.get("/se-debe/")

    assert respuesta.status_code == 200
    assert "Nadie te debe nada registrado" in respuesta.content.decode()


# --- La arquitectura --------------------------------------------------------


@pytest.mark.django_db
def test_un_proveedor_roto_no_tumba_la_pantalla(sesion_admin, household):
    """Un módulo con un fallo no puede dejar sin respuesta a los demás."""
    def revienta(_):
        raise RuntimeError("módulo roto")

    registry.owed_providers.append(revienta)
    try:
        assert sesion_admin.get("/se-debe/").status_code == 200
    finally:
        registry.owed_providers.remove(revienta)
