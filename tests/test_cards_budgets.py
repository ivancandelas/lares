"""Tarjetas y topes de gasto.

Dos cosas que casi ninguna app distingue:

  - el saldo de hoy no es lo que hay que pagar: eso es el saldo AL CORTE
  - un tope solo sirve si avisa a tiempo, no el día 31
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Obligation, Posting
from lares.core.services import checks, obligations
from lares.modules.finance import services
from lares.modules.finance.models import CreditCard
from lares.modules.finance.models_budget import Budget

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


def _comprar(household, tarjeta, importe, fecha):
    gasto, _ = Account.objects.get_or_create(household=household, name="Compras",
                                             type=Account.Type.EXPENSE)
    entry = Entry.objects.create(household=household, date=fecha,
                                 description="Compra")
    Posting.objects.create(household=household, entry=entry, account=gasto,
                           amount=importe)
    Posting.objects.create(household=household, entry=entry,
                           account=tarjeta.account, amount=-importe)


# --- El ciclo de la tarjeta -------------------------------------------------


@pytest.mark.django_db
def test_el_ultimo_corte_es_el_que_ya_paso(scoped, tarjeta):
    assert tarjeta.last_cut(dt.date(2026, 9, 20)) == dt.date(2026, 9, 17)
    # Antes del día 17, el corte vigente es el del mes anterior.
    assert tarjeta.last_cut(dt.date(2026, 9, 10)) == dt.date(2026, 8, 17)


@pytest.mark.django_db
def test_la_fecha_de_pago_es_del_mes_siguiente_al_corte(scoped, tarjeta):
    """Corta el 17 y se paga el 5: el 5 del mes siguiente."""
    assert tarjeta.next_due(dt.date(2026, 9, 20)) == dt.date(2026, 10, 5)


@pytest.mark.django_db
def test_lo_comprado_tras_el_corte_no_entra_en_este_pago(scoped, tarjeta):
    """Es lo que hace que «saldo de hoy» y «lo que hay que pagar» difieran."""
    corte = tarjeta.last_cut()
    _comprar(scoped, tarjeta, Decimal("5000"), corte - dt.timedelta(days=3))
    _comprar(scoped, tarjeta, Decimal("2000"), corte + dt.timedelta(days=1))

    assert tarjeta.account.balance == Decimal("7000")     # saldo de hoy
    assert tarjeta.no_interest_payment == Decimal("5000")  # lo que toca pagar
    assert tarjeta.after_cut == Decimal("2000")            # va al siguiente


@pytest.mark.django_db
def test_el_aviso_de_pago_usa_el_saldo_al_corte(scoped, tarjeta):
    corte = tarjeta.last_cut()
    _comprar(scoped, tarjeta, Decimal("5000"), corte - dt.timedelta(days=3))
    _comprar(scoped, tarjeta, Decimal("2000"), corte + dt.timedelta(days=1))
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.filter(source="finance.card_payment").first()
    assert aviso.amount == Decimal("5000")
    assert aviso.extra["kind"] == "no_interest"


@pytest.mark.django_db
def test_el_uso_del_limite_se_calcula_sobre_el_saldo_actual(scoped, tarjeta):
    _comprar(scoped, tarjeta, Decimal("30000"), HOY)
    assert tarjeta.usage == pytest.approx(0.5)


@pytest.mark.django_db
def test_avisa_cuando_no_alcanza_para_liquidar(scoped, tarjeta):
    """Pagar de menos genera intereses sobre todo el periodo."""
    corte = tarjeta.last_cut()
    _comprar(scoped, tarjeta, Decimal("40000"), corte - dt.timedelta(days=2))

    hallazgos = [f for f in checks.run_all(scoped)
                 if f.check == "finance.cannot_pay_full"]
    assert hallazgos
    assert "intereses sobre todo el periodo" in hallazgos[0].detail


@pytest.mark.django_db
def test_no_avisa_si_si_alcanza(scoped, tarjeta):
    banco = Account.objects.create(household=scoped, name="Nómina",
                                   type=Account.Type.ASSET)
    sueldo = Account.objects.create(household=scoped, name="Sueldo",
                                    type=Account.Type.INCOME)
    entry = Entry.objects.create(household=scoped, date=HOY, description="Nómina")
    Posting.objects.create(household=scoped, entry=entry, account=banco,
                           amount=Decimal("60000"))
    Posting.objects.create(household=scoped, entry=entry, account=sueldo,
                           amount=Decimal("-60000"))
    _comprar(scoped, tarjeta, Decimal("5000"), tarjeta.last_cut() - dt.timedelta(days=2))

    claves = {f.check for f in checks.run_all(scoped)}
    assert "finance.cannot_pay_full" not in claves


# --- Topes de gasto ---------------------------------------------------------


@pytest.fixture
def tope(scoped):
    cuenta = Account.objects.create(household=scoped, name="Supermercado",
                                    type=Account.Type.EXPENSE)
    return Budget.objects.create(household=scoped, account=cuenta,
                                 amount=Decimal("8000"))


def _gastar(household, cuenta, importe, dia):
    origen, _ = Account.objects.get_or_create(household=household, name="Banco",
                                              type=Account.Type.ASSET)
    fecha = HOY.replace(day=min(dia, 28))
    entry = Entry.objects.create(household=household, date=fecha, description="Gasto")
    Posting.objects.create(household=household, entry=entry, account=cuenta,
                           amount=importe)
    Posting.objects.create(household=household, entry=entry, account=origen,
                           amount=-importe)


@pytest.mark.django_db
def test_cuenta_solo_lo_gastado_este_mes(scoped, tope):
    _gastar(scoped, tope.account, Decimal("3000"), 5)
    mes_pasado = Entry.objects.create(
        household=scoped, date=HOY.replace(day=1) - dt.timedelta(days=5),
        description="Del mes pasado",
    )
    Posting.objects.create(household=scoped, entry=mes_pasado, account=tope.account,
                           amount=Decimal("9999"))

    linea = services.budgets(scoped)["lines"][0]
    assert linea.spent == Decimal("3000")


@pytest.mark.django_db
def test_avisa_del_ritmo_antes_de_pasarse(scoped, tope):
    """Saber el 12 que vas rápido sí cambia algo; saberlo el 31, no."""
    _gastar(scoped, tope.account, Decimal("6000"), 5)      # 75% del tope
    datos = services.budgets(scoped, on_date=HOY.replace(day=10))

    linea = datos["lines"][0]
    assert not linea.over
    assert linea.ahead
    assert linea.projected > linea.planned


@pytest.mark.django_db
def test_un_gasto_acorde_al_mes_no_genera_ruido(scoped, tope):
    _gastar(scoped, tope.account, Decimal("2400"), 5)      # 30% con 33% del mes
    datos = services.budgets(scoped, on_date=HOY.replace(day=10))

    assert not datos["lines"][0].ahead
    assert not datos["lines"][0].over


@pytest.mark.django_db
def test_pasarse_del_tope_es_un_hueco_grave(scoped, tope):
    _gastar(scoped, tope.account, Decimal("9000"), 5)

    hallazgos = [f for f in checks.run_all(scoped) if f.check == "finance.budget_pace"]
    assert hallazgos
    assert hallazgos[0].severity == "high"


@pytest.mark.django_db
def test_lo_gastado_sin_tope_no_desaparece(scoped, tope):
    """No es cero: es lo que no estás mirando."""
    otra = Account.objects.create(household=scoped, name="Otra cosa",
                                  type=Account.Type.EXPENSE)
    _gastar(scoped, tope.account, Decimal("1000"), 5)
    _gastar(scoped, otra, Decimal("4500"), 6)

    assert services.budgets(scoped)["unbudgeted"] == Decimal("4500")


# --- Previsualización de documentos ----------------------------------------


@pytest.mark.django_db
def test_un_documento_se_ve_sin_descargarlo(sesion_admin, scoped):
    from django.core.files.base import ContentFile

    from lares.core.models import Document

    doc = Document.objects.create(household=scoped, title="Póliza",
                                  mime_type="application/pdf")
    doc.file.save("poliza.pdf", ContentFile(b"%PDF-1.4 x"), save=True)

    respuesta = sesion_admin.get(f"/d/{doc.pk}/ver/")
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/pdf"
    # inline, no attachment: el navegador lo muestra.
    assert respuesta["Content-Disposition"].startswith("inline")


@pytest.mark.django_db
def test_un_documento_de_otro_hogar_no_se_abre(sesion_admin, scoped):
    """Ni conociendo su identificador."""
    from django.core.files.base import ContentFile

    from lares.core.models import Document, Household
    from lares.core.scoping import use_household

    # Creado despues: en modo mono-hogar manda el mas antiguo.
    ajeno = Household.objects.create(name="Casa ajena", slug="ajena")
    with use_household(ajeno):
        doc = Document.objects.create(household=ajeno, title="Escritura ajena")
        doc.file.save("secreto.pdf", ContentFile(b"%PDF-1.4 x"), save=True)

    assert sesion_admin.get(f"/d/{doc.pk}/ver/").status_code == 404


@pytest.mark.django_db
def test_un_documento_sin_archivo_no_se_puede_ver(sesion_admin, scoped):
    from lares.core.models import Document

    doc = Document.objects.create(household=scoped, title="Solo metadatos")
    assert sesion_admin.get(f"/d/{doc.pk}/ver/").status_code == 404
