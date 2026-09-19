"""Lo que un formulario tiene que dar resuelto.

Dos cosas que no son cosmética:

  - **La moneda se elige, no se teclea.** Escribirla a mano deja «mxn», «Mxn» y
    «MX» conviviendo en la misma base, y entonces cualquier suma por moneda
    deja de cuadrar.
  - **El saldo va al lado de la cuenta.** Elegir de dónde sale el dinero sin
    verlo obliga a abrir otra pantalla y volver; es el dato que hace falta
    justo en ese momento y del que salen los sobregiros.

Las dos están resueltas en la base común, no en cada formulario, así que lo que
se prueba es que valen para cualquiera.
"""

import datetime as dt
import re
from decimal import Decimal

import pytest

from lares.core.forms import MONEDAS, AccountForm, ExpenseForm, TransferForm
from lares.core.models import Account, Entry, Posting

HOY = dt.date.today()


def _cuenta(household, nombre, tipo=Account.Type.ASSET, moneda="MXN"):
    return Account.objects.create(household=household, name=nombre, type=tipo,
                                  currency=moneda)


def _mover(household, cuenta, importe, contra):
    entry = Entry.objects.create(household=household, date=HOY,
                                 description="Movimiento")
    Posting.objects.create(household=household, entry=entry, account=cuenta,
                           amount=Decimal(importe))
    Posting.objects.create(household=household, entry=entry, account=contra,
                           amount=-Decimal(importe))


def _opciones(campo) -> list:
    return [str(etiqueta) for _, etiqueta in campo.field.choices]


# --- La moneda se elige -----------------------------------------------------


@pytest.mark.django_db
def test_la_moneda_es_un_desplegable(scoped):
    form = AccountForm(household=scoped)

    assert form.fields["currency"].choices
    assert "MXN" in [c for c, _ in form.fields["currency"].choices]


@pytest.mark.django_db
def test_la_moneda_del_hogar_va_primero(scoped):
    """Es la que se elige el 95% de las veces."""
    scoped.currency = "USD"
    scoped.save()
    form = AccountForm(household=scoped)

    assert [c for c, _ in form.fields["currency"].choices][0] == "USD"


@pytest.mark.django_db
def test_no_se_repite_la_moneda_del_hogar(scoped):
    codigos = [c for c, _ in AccountForm(household=scoped)
               .fields["currency"].choices]

    assert len(codigos) == len(set(codigos))


@pytest.mark.django_db
def test_una_moneda_rara_ya_guardada_se_sigue_pudiendo_elegir(scoped):
    """Si no, editar esa cuenta le cambiaría la moneda sin avisar."""
    cuenta = _cuenta(scoped, "Cuenta en Noruega", moneda="NOK")
    assert "NOK" not in MONEDAS

    codigos = [c for c, _ in AccountForm(instance=cuenta, household=scoped)
               .fields["currency"].choices]
    assert "NOK" in codigos


@pytest.mark.django_db
def test_editar_no_cambia_la_moneda_que_ya_tenia(scoped):
    cuenta = _cuenta(scoped, "Ahorro", moneda="USD")
    form = AccountForm(instance=cuenta, household=scoped)

    assert form.fields["currency"].initial == "USD"


@pytest.mark.django_db
def test_la_moneda_llega_a_la_pantalla_como_select(sesion_admin, household):
    html = sesion_admin.get("/cuentas/nueva/").content.decode()
    bloque = re.search(r'<select[^>]*name="currency".*?</select>', html, re.S)

    assert bloque, "la moneda se sigue tecleando"
    assert "MXN" in bloque.group(0)


# --- El saldo al lado de la cuenta ------------------------------------------


@pytest.mark.django_db
def test_el_desplegable_de_cuentas_muestra_su_saldo(scoped):
    banco = _cuenta(scoped, "Nómina")
    gasto = _cuenta(scoped, "Súper", Account.Type.EXPENSE)
    _mover(scoped, banco, 41850, gasto)

    form = TransferForm(household=scoped)
    etiquetas = _opciones(form["origin"])

    assert any("Nómina" in e and "41,850" in e for e in etiquetas), etiquetas


@pytest.mark.django_db
def test_una_deuda_se_muestra_por_lo_que_debes(scoped):
    """Nadie dice «debo menos catorce mil»."""
    tarjeta = _cuenta(scoped, "Tarjeta", Account.Type.LIABILITY)
    gasto = _cuenta(scoped, "Compras", Account.Type.EXPENSE)
    _mover(scoped, gasto, 29700, tarjeta)

    etiquetas = _opciones(TransferForm(household=scoped)["destination"])
    assert any("Tarjeta" in e and "29,700" in e for e in etiquetas), etiquetas


@pytest.mark.django_db
def test_el_saldo_tambien_sale_al_registrar_un_gasto(scoped):
    banco = _cuenta(scoped, "Nómina")
    gasto = _cuenta(scoped, "Súper", Account.Type.EXPENSE)
    _mover(scoped, banco, 5000, gasto)

    etiquetas = _opciones(ExpenseForm(household=scoped)["paid_from"])
    assert any("5,000" in e for e in etiquetas), etiquetas


@pytest.mark.django_db
def test_la_categoria_no_lleva_saldo(scoped):
    """El saldo de «Gastos: súper» no significa nada al elegir categoría."""
    _cuenta(scoped, "Nómina")
    gasto = _cuenta(scoped, "Súper", Account.Type.EXPENSE)
    _mover(scoped, gasto, 5000, _cuenta(scoped, "Otra"))

    etiquetas = _opciones(ExpenseForm(household=scoped)["category"])
    assert all("·" not in e for e in etiquetas), etiquetas


@pytest.mark.django_db
def test_los_saldos_salen_en_una_sola_consulta(scoped, django_assert_num_queries):
    """Una consulta por cuenta convierte el desplegable en un N+1."""
    contra = _cuenta(scoped, "Contra", Account.Type.EXPENSE)
    for i in range(12):
        _mover(scoped, _cuenta(scoped, f"Cuenta {i}"), 1000 + i, contra)

    with django_assert_num_queries(1):
        Account.balances(scoped)


@pytest.mark.django_db
def test_el_saldo_agregado_coincide_con_el_de_cada_cuenta(scoped):
    """La versión rápida y la lenta tienen que decir lo mismo."""
    banco = _cuenta(scoped, "Nómina")
    tarjeta = _cuenta(scoped, "Tarjeta", Account.Type.LIABILITY)
    gasto = _cuenta(scoped, "Súper", Account.Type.EXPENSE)
    _mover(scoped, banco, 41850, gasto)
    _mover(scoped, gasto, 29700, tarjeta)

    saldos = Account.balances(scoped)
    for cuenta in (banco, tarjeta, gasto):
        assert saldos[cuenta.pk] == cuenta.balance, cuenta.name


@pytest.mark.django_db
def test_una_cuenta_sin_movimientos_sale_en_cero(scoped):
    _cuenta(scoped, "Recién abierta")

    etiquetas = _opciones(TransferForm(household=scoped)["origin"])
    assert any("Recién abierta" in e and "0.00" in e for e in etiquetas)
