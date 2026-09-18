"""Préstamos, en los dos sentidos.

Casi todo el software de finanzas personales asume que solo *debes* dinero. El
que diste es el que se evapora, porque no llega un recibo cada mes que te lo
recuerde. Eso es lo que prueba este archivo.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Obligation, Party, Resource
from lares.core.registry import registry
from lares.core.services import checks, obligations
from lares.modules.loans.models import Loan, LoanPayment

HOY = dt.date.today()


def _loan(household, **kwargs):
    datos = dict(kind="loan", name="Préstamo", principal=Decimal("60000"),
                 direction=Loan.Direction.LENT, currency="MXN")
    datos.update(kwargs)
    return Loan.objects.create(household=household, **datos)


# --- Saldo ------------------------------------------------------------------


@pytest.mark.django_db
def test_los_abonos_bajan_el_saldo(scoped):
    prestamo = _loan(scoped)
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("5000"))

    prestamo.refresh_from_db()
    assert prestamo.paid == 5000
    assert prestamo.outstanding == 55000


@pytest.mark.django_db
def test_sin_desglose_todo_cuenta_como_capital(scoped):
    """Es lo correcto en los préstamos de palabra, que son la mayoría."""
    prestamo = _loan(scoped)
    abono = LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                                       amount=Decimal("5000"))
    assert abono.principal_part == 5000


@pytest.mark.django_db
def test_los_intereses_no_bajan_el_capital(scoped):
    """Pagar 17,180 de los que 15,050 son interés baja el saldo en 2,130."""
    prestamo = _loan(scoped, name="Hipoteca", principal=Decimal("1720000"),
                     direction=Loan.Direction.BORROWED)
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("17180"),
                               principal_part=Decimal("2130"),
                               interest_part=Decimal("15050"))

    assert prestamo.outstanding == Decimal("1717870")
    assert prestamo.interest_paid == 15050


# --- Dirección --------------------------------------------------------------


@pytest.mark.django_db
def test_lo_que_te_deben_suma_al_patrimonio(scoped):
    prestado = _loan(scoped, direction=Loan.Direction.LENT)
    assert prestado.counts_as_asset
    assert prestado.current_value == 60000


@pytest.mark.django_db
def test_lo_que_debes_no_suma(scoped):
    debido = _loan(scoped, direction=Loan.Direction.BORROWED)
    assert not debido.counts_as_asset
    assert debido.current_value is None


@pytest.mark.django_db
def test_el_valor_baja_con_cada_abono(scoped):
    """Un préstamo vale lo que queda por cobrar, no su importe original."""
    prestamo = _loan(scoped, direction=Loan.Direction.LENT)
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("10000"))

    prestamo.refresh_from_db()
    assert prestamo.current_value == 50000
    assert Resource.objects.get(pk=prestamo.pk).current_value == 50000


@pytest.mark.django_db
def test_uno_pagado_deja_de_contar(scoped):
    prestamo = _loan(scoped, principal=Decimal("5000"))
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("5000"))

    prestamo.refresh_from_db()
    assert prestamo.is_settled
    assert not prestamo.counts_as_asset


@pytest.mark.django_db
def test_darlo_por_perdido_lo_saca_del_patrimonio_sin_borrarlo(scoped):
    prestamo = _loan(scoped)
    prestamo.state = Loan.State.FORGIVEN
    prestamo.save()

    assert prestamo.outstanding == 0
    assert not prestamo.counts_as_asset
    assert Loan.objects.filter(pk=prestamo.pk).exists()


# --- Avisos -----------------------------------------------------------------


@pytest.mark.django_db
def test_cobrar_es_una_obligacion_como_pagar(scoped):
    luis = Party.objects.create(household=scoped, name="Luis")
    _loan(scoped, name="Préstamo a Luis", counterpart=luis,
          payment_amount=Decimal("5000"), payment_day=15)
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.filter(source="loans.payment").first()
    assert aviso.title.startswith("Cobrar")
    assert str(aviso.counterparty) == "Luis"


@pytest.mark.django_db
def test_dejar_de_pagar_es_mas_urgente_que_dejar_de_cobrar(scoped):
    """No pagar tiene consecuencias inmediatas; no cobrar se nota un año después."""
    _loan(scoped, name="Hipoteca", direction=Loan.Direction.BORROWED,
          payment_amount=Decimal("17180"), payment_day=5)
    _loan(scoped, name="A Luis", direction=Loan.Direction.LENT,
          payment_amount=Decimal("5000"), payment_day=15)
    obligations.materialize(scoped, HOY)

    debo = Obligation.objects.filter(title__startswith="Pagar").first()
    cobro = Obligation.objects.filter(title__startswith="Cobrar").first()
    assert debo.severity == "high"
    assert cobro.severity == "normal"


@pytest.mark.django_db
def test_la_cuota_nunca_pide_mas_de_lo_que_queda(scoped):
    _loan(scoped, principal=Decimal("3000"),
          payment_amount=Decimal("5000"), payment_day=15)
    obligations.materialize(scoped, HOY)

    assert Obligation.objects.filter(source="loans.payment").first().amount == 3000


@pytest.mark.django_db
def test_uno_saldado_deja_de_avisar(scoped):
    prestamo = _loan(scoped, principal=Decimal("5000"),
                     payment_amount=Decimal("5000"), payment_day=15)
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("5000"))
    Obligation.objects.all().delete()
    obligations.materialize(scoped, HOY)

    assert not Obligation.objects.filter(source="loans.payment").exists()


# --- Huecos -----------------------------------------------------------------


@pytest.mark.django_db
def test_avisa_del_prestamo_que_nadie_esta_pagando(scoped):
    """El hueco característico: cuando te deben no llega ningún recibo."""
    _loan(scoped, name="A mi hermano", started_on=HOY - dt.timedelta(days=400))

    hallazgos = [f for f in checks.run_all(scoped) if f.check == "loans.forgotten"]
    assert hallazgos
    assert hallazgos[0].severity == "high"


@pytest.mark.django_db
def test_no_avisa_de_uno_que_se_esta_pagando(scoped):
    prestamo = _loan(scoped, started_on=HOY - dt.timedelta(days=400))
    LoanPayment.objects.create(household=scoped, loan=prestamo, date=HOY,
                               amount=Decimal("5000"))

    claves = {f.check for f in checks.run_all(scoped)}
    assert "loans.forgotten" not in claves


@pytest.mark.django_db
def test_no_reclama_por_lo_que_tu_debes(scoped):
    """Que tú no pagues es otra cosa, y ya avisa la obligación."""
    _loan(scoped, direction=Loan.Direction.BORROWED,
          started_on=HOY - dt.timedelta(days=400))

    claves = {f.check for f in checks.run_all(scoped)}
    assert "loans.forgotten" not in claves


@pytest.mark.django_db
def test_avisa_de_uno_de_palabra_y_grande_sin_nada_escrito(scoped):
    _loan(scoped, principal=Decimal("60000"), is_informal=True, description="")

    claves = {f.check for f in checks.run_all(scoped)}
    assert "loans.no_record" in claves


@pytest.mark.django_db
def test_no_molesta_con_lo_pequeno(scoped):
    _loan(scoped, principal=Decimal("500"), is_informal=True)

    claves = {f.check for f in checks.run_all(scoped)}
    assert "loans.no_record" not in claves


# --- Amortización -----------------------------------------------------------


@pytest.mark.django_db
def test_la_tabla_amortiza_de_verdad(scoped):
    prestamo = _loan(scoped, name="Hipoteca", principal=Decimal("1720000"),
                     direction=Loan.Direction.BORROWED,
                     interest_kind=Loan.Interest.AMORTIZED,
                     annual_rate=Decimal("10.5"), term_months=240,
                     payment_amount=Decimal("17180"),
                     started_on=dt.date(2021, 9, 1))
    tabla = prestamo.amortization(limit=3)

    assert len(tabla) == 3
    # El interés baja y el capital sube: eso es amortizar.
    assert tabla[0]["interest"] > tabla[2]["interest"]
    assert tabla[0]["principal"] < tabla[2]["principal"]
    assert tabla[2]["balance"] < tabla[0]["balance"]


@pytest.mark.django_db
def test_sin_cuota_no_hay_tabla(scoped):
    assert _loan(scoped).amortization() == []


# --- Enlaces de ficha -------------------------------------------------------


@pytest.mark.django_db
def test_la_ficha_de_la_persona_dice_cuanto_te_debe(scoped):
    luis = Party.objects.create(household=scoped, name="Luis")
    _loan(scoped, counterpart=luis, principal=Decimal("60000"))

    enlaces = {e.label: e for e in registry.links_for(luis)}
    assert "te debe" in enlaces
    assert "$60,000" in enlaces["te debe"].hint


@pytest.mark.django_db
def test_y_cuanto_le_debes(scoped):
    banco = Party.objects.create(household=scoped, name="BBVA",
                                 kind=Party.Kind.ORGANIZATION)
    _loan(scoped, counterpart=banco, direction=Loan.Direction.BORROWED,
          principal=Decimal("1720000"))

    enlaces = {e.label: e for e in registry.links_for(banco)}
    assert "le debes" in enlaces
