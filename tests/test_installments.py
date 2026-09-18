"""Compras a meses.

No encajan en ninguna de las dos maneras obvias de registrarlas:

    registrar el total       → el sistema pide pagar 12.000 este mes cuando el
                               banco solo cobra 1.000
    registrar la mensualidad → la deuda real queda subestimada en 11.000

Las dos mienten en algo distinto. Lo correcto es separar lo que *debes* de lo
que *te cobran*.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Obligation, Posting
from lares.core.services import checks, obligations
from lares.modules.finance import services
from lares.modules.finance.forms import InstallmentPlanForm
from lares.modules.finance.models import CreditCard
from lares.modules.finance.models_installment import InstallmentPlan

HOY = dt.date.today()


@pytest.fixture
def tarjeta(scoped):
    cuenta = Account.objects.create(household=scoped, name="Tarjeta",
                                    type=Account.Type.LIABILITY, currency="MXN")
    return CreditCard.objects.create(
        household=scoped, name="Tarjeta BBVA", kind="credit_card", account=cuenta,
        last_four="1234", credit_limit=Decimal("60000"), cut_day=17, due_day=5,
        currency="MXN",
    )


@pytest.fixture
def categoria(scoped):
    return Account.objects.create(household=scoped, name="Electrónica",
                                  type=Account.Type.EXPENSE)


def _hace_meses(n: int) -> dt.date:
    """Exactamente n meses atrás. Restar 31 días por mes no da meses."""
    total = HOY.month - 1 - n
    ano = HOY.year + total // 12
    return dt.date(ano, total % 12 + 1, 1)


def _plan(scoped, tarjeta, categoria, total="12000", meses=12, hace_meses=0):
    form = InstallmentPlanForm({
        "description": "Refrigerador", "card": tarjeta.pk, "category": categoria.pk,
        "total_amount": total, "months": str(meses),
        "first_charge_on": _hace_meses(hace_meses).isoformat(),
        "interest_free": "on",
    }, household=scoped)
    assert form.is_valid(), form.errors
    return form.save()


# --- La deuda existe desde el primer día ------------------------------------


@pytest.mark.django_db
def test_el_asiento_se_hace_por_el_total_no_por_la_mensualidad(scoped, tarjeta,
                                                               categoria):
    """La deuda es de 12.000 desde que firmas, aunque te la cobren poco a poco."""
    plan = _plan(scoped, tarjeta, categoria)

    assert plan.entry.postings.filter(amount__gt=0).first().amount == Decimal("12000")
    assert tarjeta.account.balance == Decimal("12000")


@pytest.mark.django_db
def test_el_patrimonio_cuenta_la_deuda_entera(scoped, tarjeta, categoria):
    _plan(scoped, tarjeta, categoria)
    assert services.net_worth(scoped)["account_debt"] == Decimal("12000")


@pytest.mark.django_db
def test_la_mensualidad_sale_del_total_entre_los_meses(scoped, tarjeta, categoria):
    plan = _plan(scoped, tarjeta, categoria, total="12000", meses=12)
    assert plan.installment == Decimal("1000.00")


# --- Pero solo te cobran una mensualidad por corte --------------------------


@pytest.mark.django_db
def test_lo_diferido_es_lo_que_aun_no_te_exigen(scoped, tarjeta, categoria):
    plan = _plan(scoped, tarjeta, categoria, hace_meses=4)

    # Cinco cargos hechos (el primero cuenta), siete pendientes.
    assert plan.charged_by() == 5
    assert plan.deferred_at() == Decimal("7000.00")


@pytest.mark.django_db
def test_el_pago_sin_intereses_descuenta_lo_diferido(scoped, tarjeta, categoria):
    """Pagar el saldo entero adelantaría mensualidades que nadie pidió."""
    _plan(scoped, tarjeta, categoria, hace_meses=4)

    assert tarjeta.account.balance == Decimal("12000")
    assert tarjeta.deferred == Decimal("7000.00")
    assert tarjeta.no_interest_payment == Decimal("5000.00")


@pytest.mark.django_db
def test_una_compra_a_un_solo_pago_se_exige_entera(scoped, tarjeta, categoria):
    """Sin plan a meses, el saldo al corte es lo que hay que pagar."""
    corte = tarjeta.last_cut()
    entry = Entry.objects.create(household=scoped, date=corte - dt.timedelta(days=2),
                                 description="Compra de contado")
    Posting.objects.create(household=scoped, entry=entry, account=categoria,
                           amount=Decimal("3000"))
    Posting.objects.create(household=scoped, entry=entry, account=tarjeta.account,
                           amount=Decimal("-3000"))

    assert tarjeta.deferred == Decimal(0)
    assert tarjeta.no_interest_payment == Decimal("3000")


@pytest.mark.django_db
def test_el_aviso_de_pago_usa_la_cifra_correcta(scoped, tarjeta, categoria):
    _plan(scoped, tarjeta, categoria, hace_meses=4)
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.filter(source="finance.card_payment").first()
    assert aviso.amount == Decimal("5000.00")       # no los 12.000


# --- Cuando termina ---------------------------------------------------------


@pytest.mark.django_db
def test_al_acabar_deja_de_diferir_nada(scoped, tarjeta, categoria):
    plan = _plan(scoped, tarjeta, categoria, meses=3, hace_meses=6)

    assert plan.is_finished
    assert plan.deferred_at() == Decimal(0)
    assert tarjeta.no_interest_payment == Decimal("12000")


@pytest.mark.django_db
def test_antes_del_primer_cargo_no_hay_nada_cobrado(scoped, tarjeta, categoria):
    plan = InstallmentPlan.objects.create(
        household=scoped, card=tarjeta, description="Futuro",
        total_amount=Decimal("6000"), months=6,
        first_charge_on=HOY + dt.timedelta(days=40),
    )
    assert plan.charged_by() == 0
    assert plan.deferred_at() == Decimal("6000.00")


# --- Lo que compromete cada mes ---------------------------------------------


@pytest.mark.django_db
def test_las_mensualidades_cuentan_como_gasto_fijo(scoped, tarjeta, categoria):
    """Una compra a meses duele los once meses siguientes, no el día que se hace."""
    _plan(scoped, tarjeta, categoria, total="12000", meses=12, hace_meses=1)

    assert tarjeta.monthly_installments == Decimal("1000.00")
    assert services.health(scoped)["fixed_monthly"] >= Decimal("1000")


@pytest.mark.django_db
def test_una_compra_terminada_ya_no_compromete_nada(scoped, tarjeta, categoria):
    _plan(scoped, tarjeta, categoria, meses=3, hace_meses=6)
    assert tarjeta.monthly_installments == Decimal(0)


@pytest.mark.django_db
def test_avisa_de_lo_que_llevas_comprometido(scoped, tarjeta, categoria):
    _plan(scoped, tarjeta, categoria, hace_meses=1)

    hallazgos = [f for f in checks.run_all(scoped)
                 if f.check == "finance.installments"]
    assert hallazgos
    assert "1,000" in hallazgos[0].title


# --- Pantalla ---------------------------------------------------------------


@pytest.mark.django_db
def test_la_ficha_de_la_tarjeta_separa_las_tres_cifras(sesion_admin, household,
                                                       scoped, tarjeta, categoria):
    _plan(scoped, tarjeta, categoria, hace_meses=4)
    contenido = sesion_admin.get(f"/dinero/tarjeta/{tarjeta.pk}/").content.decode()

    assert "Debes en total" in contenido
    assert "De eso, a meses" in contenido
    assert "Para no pagar intereses" in contenido


# --- A meses con intereses --------------------------------------------------


@pytest.mark.django_db
def test_con_intereses_la_mensualidad_no_es_el_total_entre_los_meses(scoped, tarjeta,
                                                                     categoria):
    """El banco solo enseña la mensualidad; la diferencia es lo que cuesta."""
    form = InstallmentPlanForm({
        "description": "Pantalla", "card": tarjeta.pk, "category": categoria.pk,
        "total_amount": "12000", "months": "12",
        "first_charge_on": _hace_meses(0).isoformat(),
        "installment_amount": "1150",
    }, household=scoped)
    assert form.is_valid(), form.errors
    plan = form.save()

    assert plan.installment == Decimal("1150")
    assert plan.total_to_pay == Decimal("13800.00")
    assert plan.interest_total == Decimal("1800.00")
    assert plan.interest_share == pytest.approx(0.15)


@pytest.mark.django_db
def test_los_intereses_no_son_deuda_de_hoy(scoped, tarjeta, categoria):
    """El libro registra el precio; los intereses son gasto de cada mes."""
    plan = InstallmentPlan.objects.create(
        household=scoped, card=tarjeta, description="Pantalla",
        total_amount=Decimal("12000"), months=12,
        first_charge_on=_hace_meses(0), interest_free=False,
        installment_amount=Decimal("1150"),
    )
    # Lo diferido se mide sobre el capital, no sobre la mensualidad.
    assert plan.principal_per_month == Decimal("1000.00")
    assert plan.deferred_at() == Decimal("11000.00")
    # Pero lo que falta por desembolsar sí incluye intereses.
    assert plan.remaining == Decimal("12650.00")


@pytest.mark.django_db
def test_sin_intereses_no_cuesta_nada_pagar_a_plazos(scoped, tarjeta, categoria):
    plan = _plan(scoped, tarjeta, categoria)
    assert plan.interest_total == Decimal(0)
    assert plan.total_to_pay == plan.total_amount


@pytest.mark.django_db
def test_con_intereses_hay_que_decir_la_mensualidad(scoped, tarjeta, categoria):
    """Calcularla nosotros sería inventar la comisión y el redondeo del banco."""
    form = InstallmentPlanForm({
        "description": "Pantalla", "card": tarjeta.pk, "category": categoria.pk,
        "total_amount": "12000", "months": "12",
        "first_charge_on": _hace_meses(0).isoformat(),
    }, household=scoped)

    assert not form.is_valid()
    assert "no es el total entre" in str(form.errors["installment_amount"])


@pytest.mark.django_db
def test_avisa_de_lo_que_cuestan_los_intereses(scoped, tarjeta, categoria):
    InstallmentPlan.objects.create(
        household=scoped, card=tarjeta, description="Pantalla",
        total_amount=Decimal("12000"), months=12,
        first_charge_on=_hace_meses(1), interest_free=False,
        installment_amount=Decimal("1150"),
    )
    hallazgos = [f for f in checks.run_all(scoped)
                 if f.check == "finance.installment_interest"]

    assert hallazgos
    assert "1,800" in hallazgos[0].title
    assert "15%" in hallazgos[0].detail


@pytest.mark.django_db
def test_lo_comprometido_al_mes_usa_la_mensualidad_real(scoped, tarjeta, categoria):
    InstallmentPlan.objects.create(
        household=scoped, card=tarjeta, description="Pantalla",
        total_amount=Decimal("12000"), months=12,
        first_charge_on=_hace_meses(1), interest_free=False,
        installment_amount=Decimal("1150"),
    )
    assert tarjeta.monthly_installments == Decimal("1150")
