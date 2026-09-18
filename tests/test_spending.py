"""«En qué se va»: cuatro preguntas distintas sobre el mismo gasto.

Meter todo en "categoría" es lo que hace que casi ninguna app de finanzas
personales pueda responder «¿cuánto llevo en Walmart?» ni «¿cuánto le he dado
a mi hijo?».
"""

import datetime as dt

import pytest

from lares.core.models import Account, Entry, Party, Posting
from lares.core.services import spending
from lares.modules.vehicles.models import Vehicle

HOY = dt.date.today()


@pytest.fixture
def libro(scoped, me):
    cuentas = {
        "tarjeta": Account.objects.create(household=scoped, name="Tarjeta",
                                          type=Account.Type.LIABILITY),
        "super": Account.objects.create(household=scoped, name="Supermercado",
                                        type=Account.Type.EXPENSE),
        "auto": Account.objects.create(household=scoped, name="Vehículo",
                                       type=Account.Type.EXPENSE),
        "familia": Account.objects.create(household=scoped, name="Familia",
                                          type=Account.Type.EXPENSE),
    }
    partes = {
        "walmart": Party.objects.create(household=scoped, name="Walmart",
                                        kind=Party.Kind.ORGANIZATION),
        "pemex": Party.objects.create(household=scoped, name="Pemex",
                                      kind=Party.Kind.ORGANIZATION),
        "hijo": Party.objects.create(household=scoped, name="Diego"),
    }
    mazda = Vehicle.objects.create(household=scoped, name="Mazda CX-5",
                                   kind="vehicle", owner=me)
    return cuentas, partes, mazda


def _gastar(household, cuentas, categoria, importe, *, dias=1, comercio=None,
            para=None, sobre=None, concepto="Compra"):
    entry = Entry.objects.create(
        household=household, date=HOY - dt.timedelta(days=dias),
        description=concepto, counterparty=comercio,
    )
    Posting.objects.create(household=household, entry=entry, account=categoria,
                           amount=importe, beneficiary=para, dimension=sobre)
    Posting.objects.create(household=household, entry=entry,
                           account=cuentas["tarjeta"], amount=-importe)
    return entry


@pytest.mark.django_db
def test_cuanto_llevo_gastado_en_walmart(scoped, libro):
    cuentas, partes, _ = libro
    _gastar(scoped, cuentas, cuentas["super"], 2340, comercio=partes["walmart"])
    _gastar(scoped, cuentas, cuentas["super"], 1980, comercio=partes["walmart"])
    _gastar(scoped, cuentas, cuentas["auto"], 980, comercio=partes["pemex"])

    filas = {f.label: f for f in spending.report(scoped, "year")["by_merchant"]}
    assert filas["Walmart"].total == 4320
    assert filas["Walmart"].count == 2


@pytest.mark.django_db
def test_y_en_que_categorias_compro_ahi(scoped, libro):
    cuentas, partes, _ = libro
    _gastar(scoped, cuentas, cuentas["super"], 2340, comercio=partes["walmart"])
    _gastar(scoped, cuentas, cuentas["familia"], 1890, comercio=partes["walmart"],
            para=partes["hijo"], concepto="Zapatos")

    detalle = spending.merchant_detail(scoped, partes["walmart"], "year")
    assert detalle["total"] == 4230
    assert {f.label for f in detalle["by_category"]} == {"Supermercado", "Familia"}


@pytest.mark.django_db
def test_cuanto_le_he_dado_a_mi_hijo(scoped, libro):
    cuentas, partes, _ = libro
    _gastar(scoped, cuentas, cuentas["familia"], 1500, para=partes["hijo"],
            concepto="Mesada")
    _gastar(scoped, cuentas, cuentas["familia"], 1890, comercio=partes["walmart"],
            para=partes["hijo"], concepto="Zapatos")
    _gastar(scoped, cuentas, cuentas["super"], 2340, comercio=partes["walmart"])

    filas = {f.label: f for f in spending.report(scoped, "year")["by_person"]}
    assert filas["Diego"].total == 3390
    # Lo que no lleva nombre es del hogar, no de nadie.
    assert filas["Del hogar"].total == 2340


@pytest.mark.django_db
def test_el_comercio_y_la_persona_son_ejes_distintos(scoped, libro):
    """Comprar en Walmart para el hijo cuenta en los dos, sin duplicar el total."""
    cuentas, partes, _ = libro
    _gastar(scoped, cuentas, cuentas["familia"], 1890, comercio=partes["walmart"],
            para=partes["hijo"])

    reporte = spending.report(scoped, "year")
    assert reporte["total"] == 1890
    assert reporte["by_merchant"][0].label == "Walmart"
    assert reporte["by_person"][0].label == "Diego"


@pytest.mark.django_db
def test_cuanto_me_cuesta_el_coche(scoped, libro):
    cuentas, partes, mazda = libro
    _gastar(scoped, cuentas, cuentas["auto"], 980, comercio=partes["pemex"], sobre=mazda)
    _gastar(scoped, cuentas, cuentas["auto"], 4750, sobre=mazda, concepto="Servicio")
    _gastar(scoped, cuentas, cuentas["super"], 2340, comercio=partes["walmart"])

    filas = {f.label: f for f in spending.report(scoped, "year")["by_thing"]}
    assert filas["Mazda CX-5"].total == 5730


@pytest.mark.django_db
def test_el_periodo_acota_de_verdad(scoped, libro):
    cuentas, partes, _ = libro
    _gastar(scoped, cuentas, cuentas["super"], 1000, dias=5, comercio=partes["walmart"])
    _gastar(scoped, cuentas, cuentas["super"], 9000, dias=200, comercio=partes["walmart"])

    assert spending.report(scoped, "month")["total"] == 1000
    assert spending.report(scoped, "year")["total"] == 10000


@pytest.mark.django_db
def test_los_ingresos_no_cuentan_como_gasto(scoped, libro):
    cuentas, _, _ = libro
    sueldo = Account.objects.create(household=scoped, name="Sueldo",
                                    type=Account.Type.INCOME)
    nomina = Account.objects.create(household=scoped, name="Nómina",
                                    type=Account.Type.ASSET)
    entry = Entry.objects.create(household=scoped, date=HOY, description="Nómina")
    Posting.objects.create(household=scoped, entry=entry, account=nomina, amount=42000)
    Posting.objects.create(household=scoped, entry=entry, account=sueldo, amount=-42000)

    assert spending.report(scoped, "year")["total"] == 0


@pytest.mark.django_db
def test_cada_comercio_enlaza_a_su_detalle(scoped, libro):
    cuentas, partes, _ = libro
    _gastar(scoped, cuentas, cuentas["super"], 2340, comercio=partes["walmart"])

    fila = spending.report(scoped, "year")["by_merchant"][0]
    assert fila.url == f"/dinero/con/{partes['walmart'].pk}/"


@pytest.mark.django_db
def test_el_formulario_de_gasto_guarda_los_tres_ejes(scoped, libro):
    from lares.core.forms import ExpenseForm

    cuentas, partes, mazda = libro
    form = ExpenseForm({
        "date": str(HOY), "description": "Gasolina", "amount": "980",
        "paid_from": cuentas["tarjeta"].pk, "category": cuentas["auto"].pk,
        "merchant": partes["pemex"].pk, "about": mazda.pk,
        "for_whom": partes["hijo"].pk,
    }, household=scoped)
    assert form.is_valid(), form.errors
    entry = form.save()

    apunte = entry.postings.get(amount__gt=0)
    assert entry.counterparty == partes["pemex"]
    assert apunte.beneficiary == partes["hijo"]
    assert apunte.dimension_id == mazda.pk
