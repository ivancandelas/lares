"""El dinero se lleva en partida doble. El saldo se calcula, no se guarda."""

import datetime as dt

import pytest

from lares.core.models import Account, Entry, Obligation, Posting
from lares.core.services import obligations
from lares.modules.finance.models import CreditCard

HOY = dt.date(2026, 9, 18)


@pytest.fixture
def tarjeta(scoped):
    cuenta = Account.objects.create(
        household=scoped, name="Tarjeta", type=Account.Type.LIABILITY, currency="MXN"
    )
    return CreditCard.objects.create(
        household=scoped, name="Tarjeta BBVA", kind="credit_card", account=cuenta,
        last_four="1234", credit_limit=10000, cut_day=17, due_day=5, currency="MXN",
    )


def _gastar(household, cuenta, importe, concepto="Compra"):
    gasto, _ = Account.objects.get_or_create(
        household=household, name="Gastos", type=Account.Type.EXPENSE
    )
    entry = Entry.objects.create(household=household, date=HOY, description=concepto)
    Posting.objects.create(household=household, entry=entry, account=gasto, amount=importe)
    Posting.objects.create(household=household, entry=entry, account=cuenta, amount=-importe)
    return entry


@pytest.mark.django_db
def test_el_asiento_cuadra_en_cero(scoped, tarjeta):
    entry = _gastar(scoped, tarjeta.account, 980)
    assert entry.is_balanced


@pytest.mark.django_db
def test_el_saldo_sale_de_los_apuntes(scoped, tarjeta):
    _gastar(scoped, tarjeta.account, 980)
    _gastar(scoped, tarjeta.account, 2340)
    # Un pasivo se muestra en positivo: "debes 3320", no "-3320".
    assert tarjeta.account.balance == 3320
    assert tarjeta.available == 6680


@pytest.mark.django_db
def test_una_correccion_es_un_asiento_inverso_no_una_edicion(scoped, tarjeta):
    original = _gastar(scoped, tarjeta.account, 5000, "Cargo duplicado")
    assert tarjeta.account.balance == 5000

    inverso = Entry.objects.create(
        household=scoped, date=HOY, description="Reverso", reverses=original
    )
    for posting in original.postings.all():
        Posting.objects.create(household=scoped, entry=inverso,
                               account=posting.account, amount=-posting.amount)

    assert tarjeta.account.balance == 0
    assert Entry.objects.count() == 2       # el historial conserva ambos


@pytest.mark.django_db
def test_la_tarjeta_genera_su_pago_mensual(scoped, tarjeta):
    """El importe es el saldo AL CORTE, no el de hoy.

    Una compra hecha despues del corte pertenece al periodo siguiente: incluirla
    haria pagar de mas.
    """
    corte = tarjeta.last_cut()
    entry = Entry.objects.create(household=scoped, date=corte - dt.timedelta(days=2),
                                 description="Compra antes del corte")
    gasto, _ = Account.objects.get_or_create(household=scoped, name="Gastos",
                                             type=Account.Type.EXPENSE)
    Posting.objects.create(household=scoped, entry=entry, account=gasto, amount=1500)
    Posting.objects.create(household=scoped, entry=entry, account=tarjeta.account,
                           amount=-1500)

    obligations.materialize(scoped, HOY)

    pagos = Obligation.objects.filter(source="finance.card_payment")
    assert pagos.count() == 2
    assert pagos.first().amount == 1500


@pytest.mark.django_db
def test_avisa_cuando_la_tarjeta_roza_el_limite(scoped, tarjeta):
    from lares.core.services import checks

    _gastar(scoped, tarjeta.account, 9500)     # 95% de 10000
    claves = {f.check for f in checks.run_all(scoped)}
    assert "finance.card_over_limit" in claves


@pytest.mark.django_db
def test_la_linea_de_contexto_no_deja_comas_huerfanas(scoped):
    cuenta = Account.objects.create(
        household=scoped, name="T", type=Account.Type.LIABILITY
    )
    parcial = CreditCard.objects.create(
        household=scoped, name="Sin datos", kind="credit_card", account=cuenta, due_day=5
    )
    assert parcial.context_line() == "se paga el 5"

    vacia = CreditCard.objects.create(household=scoped, name="Nada", kind="credit_card")
    assert vacia.context_line() == ""
