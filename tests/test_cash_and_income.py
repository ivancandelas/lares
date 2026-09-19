"""Efectivo, traspasos e ingresos recurrentes.

Tres huecos que se notaban al usar el sistema, no al leerlo:

  - **el efectivo** no tenía sitio propio, y sin él un retiro del cajero no
    se puede registrar bien;
  - **no había traspaso**: mover dinero entre cuentas tuyas solo se podía
    anotar como gasto, que lo cuenta dos veces;
  - **no había ingreso recurrente**: un sueldo solo existía como promedio de
    los últimos tres meses.

Los tres se tocan: el retiro es el caso donde más se nota, porque quien lo
anota como gasto ve su dinero desaparecer dos veces.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.forms import IncomeEntryForm, TransferForm
from lares.core.models import Account, Entry, Posting
from lares.core.registry import registry
from lares.core.services import checks
from lares.modules.finance.models_income import RecurringIncome
from lares.modules.finance.services import cash_flow

HOY = dt.date.today()


def _cuenta(household, nombre, tipo=Account.Type.ASSET):
    return Account.objects.create(household=household, name=nombre, type=tipo,
                                  currency="MXN")


# --- El efectivo es una cuenta ----------------------------------------------


@pytest.mark.django_db
def test_el_efectivo_es_una_cuenta_de_activo_sin_caso_especial(scoped):
    """No hace falta un modelo aparte: el libro ya sabe manejarlo."""
    efectivo = _cuenta(scoped, "Efectivo")
    banco = _cuenta(scoped, "Banco")

    form = TransferForm({"date": HOY, "amount": "4000",
                         "origin": str(banco.pk),
                         "destination": str(efectivo.pk)}, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    assert efectivo.balance == 4000
    assert banco.balance == -4000


@pytest.mark.django_db
def test_un_retiro_no_aparece_en_en_que_se_va_el_dinero(scoped):
    """Es la razón de ser del traspaso: sacar del cajero no es gastar."""
    banco = _cuenta(scoped, "Banco")
    efectivo = _cuenta(scoped, "Efectivo")

    form = TransferForm({"date": HOY, "amount": "4000",
                         "origin": str(banco.pk),
                         "destination": str(efectivo.pk),
                         "description": "Retiro del cajero"}, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    # Ninguna cuenta de gasto quedó tocada: por eso no infla «en qué se va».
    assert not Posting.objects.filter(
        account__type=Account.Type.EXPENSE).exists()


@pytest.mark.django_db
def test_gastar_en_efectivo_baja_el_efectivo(scoped):
    efectivo = _cuenta(scoped, "Efectivo")
    despensa = _cuenta(scoped, "Despensa", Account.Type.EXPENSE)
    entry = Entry.objects.create(household=scoped, date=HOY,
                                 description="Mercado")
    Posting.objects.create(household=scoped, entry=entry, account=despensa,
                           amount=Decimal("850"))
    Posting.objects.create(household=scoped, entry=entry, account=efectivo,
                           amount=Decimal("-850"))

    assert efectivo.balance == -850          # sin retiro previo, queda negativo


@pytest.mark.django_db
def test_una_cuenta_en_negativo_salta_como_hueco(scoped):
    """No se puede gastar de una cuenta lo que nunca entró."""
    efectivo = _cuenta(scoped, "Efectivo")
    despensa = _cuenta(scoped, "Despensa", Account.Type.EXPENSE)
    entry = Entry.objects.create(household=scoped, date=HOY, description="X")
    Posting.objects.create(household=scoped, entry=entry, account=despensa,
                           amount=Decimal("850"))
    Posting.objects.create(household=scoped, entry=entry, account=efectivo,
                           amount=Decimal("-850"))

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "finance.negative_asset")
    assert "Efectivo" in hallazgo.title
    assert "traspaso" in hallazgo.detail


@pytest.mark.django_db
def test_con_el_retiro_registrado_no_salta(scoped):
    efectivo = _cuenta(scoped, "Efectivo")
    banco = _cuenta(scoped, "Banco")
    despensa = _cuenta(scoped, "Despensa", Account.Type.EXPENSE)

    form = TransferForm({"date": HOY, "amount": "4000",
                         "origin": str(banco.pk),
                         "destination": str(efectivo.pk)}, household=scoped)
    assert form.is_valid()
    form.save()
    entry = Entry.objects.create(household=scoped, date=HOY, description="X")
    Posting.objects.create(household=scoped, entry=entry, account=despensa,
                           amount=Decimal("850"))
    Posting.objects.create(household=scoped, entry=entry, account=efectivo,
                           amount=Decimal("-850"))

    assert efectivo.balance == 3150
    assert not [f for f in checks.run_all(scoped)
                if f.check == "finance.negative_asset"
                and "Efectivo" in f.title]


# --- El traspaso ------------------------------------------------------------


@pytest.mark.django_db
def test_un_traspaso_no_toca_ninguna_categoria_de_gasto(scoped):
    origen, destino = _cuenta(scoped, "Nómina"), _cuenta(scoped, "Ahorro")
    form = TransferForm({"date": HOY, "amount": "10000",
                         "origin": str(origen.pk),
                         "destination": str(destino.pk)}, household=scoped)
    assert form.is_valid()
    entry = form.save()

    assert entry.postings.count() == 2
    assert sum(p.amount for p in entry.postings.all()) == 0
    assert not entry.postings.filter(
        account__type=Account.Type.EXPENSE).exists()


@pytest.mark.django_db
def test_pagar_la_tarjeta_baja_la_deuda(scoped):
    """Un pasivo vive en negativo: abonarle sube su saldo hacia cero."""
    banco = _cuenta(scoped, "Banco")
    tarjeta = _cuenta(scoped, "Tarjeta", Account.Type.LIABILITY)
    gasto = _cuenta(scoped, "Compras", Account.Type.EXPENSE)
    compra = Entry.objects.create(household=scoped, date=HOY, description="C")
    Posting.objects.create(household=scoped, entry=compra, account=gasto,
                           amount=Decimal("5000"))
    Posting.objects.create(household=scoped, entry=compra, account=tarjeta,
                           amount=Decimal("-5000"))
    assert tarjeta.balance == 5000

    form = TransferForm({"date": HOY, "amount": "3000",
                         "origin": str(banco.pk),
                         "destination": str(tarjeta.pk)}, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    assert tarjeta.balance == 2000


@pytest.mark.django_db
def test_no_se_puede_traspasar_a_la_misma_cuenta(scoped):
    banco = _cuenta(scoped, "Banco")
    form = TransferForm({"date": HOY, "amount": "100", "origin": str(banco.pk),
                         "destination": str(banco.pk)}, household=scoped)

    assert not form.is_valid()
    assert "otra cuenta" in str(form.errors["destination"])


@pytest.mark.django_db
def test_el_traspaso_se_nombra_solo_si_no_le_pones_concepto(scoped):
    origen, destino = _cuenta(scoped, "Nómina"), _cuenta(scoped, "Ahorro")
    form = TransferForm({"date": HOY, "amount": "100",
                         "origin": str(origen.pk),
                         "destination": str(destino.pk)}, household=scoped)
    assert form.is_valid()

    assert form.save().description == "Traspaso de Nómina a Ahorro"


# --- Registrar un ingreso suelto --------------------------------------------


@pytest.mark.django_db
def test_registrar_un_ingreso_sube_la_cuenta(scoped):
    banco = _cuenta(scoped, "Banco")
    sueldo = _cuenta(scoped, "Sueldo", Account.Type.INCOME)

    form = IncomeEntryForm({"date": HOY, "description": "Nómina",
                            "amount": "42000", "into": str(banco.pk),
                            "category": str(sueldo.pk)}, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    assert banco.balance == 42000
    assert sueldo.balance == 42000        # los ingresos se muestran en positivo


# --- El sueldo declarado ----------------------------------------------------


def _sueldo(household, **kwargs):
    datos = dict(name="Nómina", amount=Decimal("42000"),
                 cycle=RecurringIncome.Cycle.MONTHLY, pay_day=30,
                 currency="MXN")
    datos.update(kwargs)
    return RecurringIncome.objects.create(household=household, **datos)


@pytest.mark.django_db
@pytest.mark.parametrize("ciclo,importe,al_mes", [
    ("monthly", 42000, 42000),
    ("biweekly", 21000, 42000),           # 24 pagas al año, no 24 medios meses
    ("yearly", 120000, 10000),
    ("weekly", 2000, "8666.67"),
])
def test_cada_ciclo_se_normaliza_al_mes(scoped, ciclo, importe, al_mes):
    ingreso = _sueldo(scoped, cycle=ciclo, amount=Decimal(importe))

    assert ingreso.per_month == Decimal(str(al_mes))


@pytest.mark.django_db
def test_el_flujo_prefiere_el_sueldo_declarado_al_promedio(scoped):
    """Un sueldo no es una estimación: se sabe cuánto es."""
    banco = _cuenta(scoped, "Banco")
    sueldo = _cuenta(scoped, "Sueldo", Account.Type.INCOME)
    entry = Entry.objects.create(household=scoped, date=HOY,
                                 description="Bono raro")
    Posting.objects.create(household=scoped, entry=entry, account=banco,
                           amount=Decimal("300000"))
    Posting.objects.create(household=scoped, entry=entry, account=sueldo,
                           amount=Decimal("-300000"))
    _sueldo(scoped)

    datos = cash_flow(scoped)
    assert datos["income_source"] == "declarado"
    assert datos["monthly_income"] == 42000        # no los 100.000 del promedio


@pytest.mark.django_db
def test_sin_sueldo_declarado_se_sigue_usando_el_promedio(scoped):
    banco = _cuenta(scoped, "Banco")
    sueldo = _cuenta(scoped, "Sueldo", Account.Type.INCOME)
    entry = Entry.objects.create(household=scoped, date=HOY, description="X")
    Posting.objects.create(household=scoped, entry=entry, account=banco,
                           amount=Decimal("30000"))
    Posting.objects.create(household=scoped, entry=entry, account=sueldo,
                           amount=Decimal("-30000"))

    assert cash_flow(scoped)["income_source"] == "promedio"


@pytest.mark.django_db
def test_un_sueldo_terminado_deja_de_contar(scoped):
    _sueldo(scoped, ends_on=HOY - dt.timedelta(days=30))

    assert cash_flow(scoped)["income_source"] == "promedio"


# --- Los dos sentidos en la pantalla de recurrentes -------------------------


@pytest.mark.django_db
def test_el_sueldo_aparece_como_lo_que_entra(scoped):
    _sueldo(scoped)

    entradas = [r for r in registry.recurring_all(scoped) if r.is_income]
    assert [r.title for r in entradas] == ["Nómina"]
    assert entradas[0].per_month == 42000


@pytest.mark.django_db
def test_la_renta_que_cobras_entra_y_la_que_pagas_sale(scoped):
    """Dejarla fuera bajaba «lo que queda» para quien vive de rentar."""
    from lares.modules.leases.models import Lease
    from lares.modules.property.models import Property

    mio = Property.objects.create(household=scoped, kind="property",
                                  name="Depto", currency="MXN")
    ajeno = Property.objects.create(household=scoped, kind="property",
                                    name="Casa", currency="MXN")
    Lease.objects.create(household=scoped, kind="lease", name="Cobro",
                         property_ref=mio, direction=Lease.Direction.LANDLORD,
                         starts_on=HOY - dt.timedelta(days=60),
                         rent_amount=Decimal("14500"), rent_day=3,
                         currency="MXN")
    Lease.objects.create(household=scoped, kind="lease", name="Pago",
                         property_ref=ajeno, direction=Lease.Direction.TENANT,
                         starts_on=HOY - dt.timedelta(days=60),
                         rent_amount=Decimal("18500"), rent_day=5,
                         currency="MXN")

    por_titulo = {r.title: r for r in registry.recurring_all(scoped)}
    assert por_titulo["Renta de Depto"].is_income
    assert not por_titulo["Renta de Casa"].is_income


@pytest.mark.django_db
def test_la_pantalla_dice_cuanto_queda(sesion_admin, household):
    _sueldo(household)
    from lares.core.models import ObligationRule

    ObligationRule.objects.create(household=household, key="cole",
                                  label="Colegiatura",
                                  schedule={"monthly": {"day": 10}},
                                  amount=Decimal("4500"), currency="MXN")

    contexto = sesion_admin.get("/recurrentes/").context
    assert contexto["entra"] == 42000
    assert contexto["al_mes"] == 4500
    assert contexto["queda"] == 37500


@pytest.mark.django_db
def test_las_pantallas_nuevas_abren(sesion_admin, household):
    ingreso = _sueldo(household)

    for url in ("/traspasos/nuevo/", "/ingresos/nuevo/",
                "/dinero/ingresos/nuevo/",
                f"/dinero/ingresos/{ingreso.pk}/"):
        assert sesion_admin.get(url).status_code == 200, url
