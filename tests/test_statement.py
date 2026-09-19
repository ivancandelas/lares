"""Estado de resultados: lo que entró, lo que salió y lo que quedó.

Se separa de «en qué se va el dinero» porque responde otra pregunta. Aquello
mira ventanas móviles —los últimos 90 días— que sirven para ver el reparto pero
**no se pueden comparar contra nada**: nadie tiene en la cabeza «los 90 días
anteriores a los últimos 90 días».

Esto usa periodos cerrados y pone el anterior al lado, que es la única pregunta
que importa: si vas mejor o peor que antes.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Posting
from lares.core.services.spending import statement

HOY = dt.date.today()
ANO = HOY.year


def _cuenta(household, nombre, tipo):
    cuenta, _ = Account.objects.get_or_create(
        household=household, name=nombre, defaults={"type": tipo})
    return cuenta


def _ingreso(household, importe, cuando, categoria="Sueldo"):
    banco = _cuenta(household, "Banco", Account.Type.ASSET)
    cat = _cuenta(household, categoria, Account.Type.INCOME)
    entry = Entry.objects.create(household=household, date=cuando,
                                 description="Ingreso")
    Posting.objects.create(household=household, entry=entry, account=banco,
                           amount=Decimal(importe))
    Posting.objects.create(household=household, entry=entry, account=cat,
                           amount=-Decimal(importe))


def _gasto(household, importe, cuando, categoria="Súper"):
    banco = _cuenta(household, "Banco", Account.Type.ASSET)
    cat = _cuenta(household, categoria, Account.Type.EXPENSE)
    entry = Entry.objects.create(household=household, date=cuando,
                                 description="Gasto")
    Posting.objects.create(household=household, entry=entry, account=cat,
                           amount=Decimal(importe))
    Posting.objects.create(household=household, entry=entry, account=banco,
                           amount=-Decimal(importe))


# --- Lo básico --------------------------------------------------------------


@pytest.mark.django_db
def test_lo_que_quedo_es_lo_que_entro_menos_lo_que_salio(scoped):
    _ingreso(scoped, 42000, dt.date(ANO, 3, 15))
    _gasto(scoped, 30000, dt.date(ANO, 3, 20))

    e = statement(scoped, ANO, 3)
    assert e.total_income == 42000
    assert e.total_expense == 30000
    assert e.result == 12000


@pytest.mark.django_db
def test_los_ingresos_se_muestran_en_positivo(scoped):
    """Nadie dice «gané menos cuarenta y dos mil»."""
    _ingreso(scoped, 42000, dt.date(ANO, 3, 15))

    assert statement(scoped, ANO, 3).income[0].amount == 42000


@pytest.mark.django_db
def test_gastar_mas_de_lo_que_entra_da_resultado_negativo(scoped):
    _ingreso(scoped, 10000, dt.date(ANO, 3, 15))
    _gasto(scoped, 25000, dt.date(ANO, 3, 20))

    e = statement(scoped, ANO, 3)
    assert e.result == -15000
    assert e.savings_rate == pytest.approx(-1.5)


@pytest.mark.django_db
def test_sin_ingresos_no_se_inventa_una_tasa_de_ahorro(scoped):
    """Dividir entre cero daría una cifra sin significado."""
    _gasto(scoped, 5000, dt.date(ANO, 3, 20))

    assert statement(scoped, ANO, 3).savings_rate is None


# --- Periodos cerrados ------------------------------------------------------


@pytest.mark.django_db
def test_un_mes_solo_cuenta_lo_de_ese_mes(scoped):
    _gasto(scoped, 5000, dt.date(ANO, 3, 31))
    _gasto(scoped, 9999, dt.date(ANO, 4, 1))

    assert statement(scoped, ANO, 3).total_expense == 5000


@pytest.mark.django_db
def test_el_ano_suma_los_doce_meses(scoped):
    _gasto(scoped, 5000, dt.date(ANO, 3, 31))
    _gasto(scoped, 4000, dt.date(ANO, 11, 1))
    _gasto(scoped, 9999, dt.date(ANO - 1, 12, 31))

    assert statement(scoped, ANO).total_expense == 9000


@pytest.mark.django_db
def test_febrero_no_se_queda_corto_ni_se_pasa(scoped):
    """El último día del mes sale de calendar, no de un 30 a ojo."""
    _gasto(scoped, 1000, dt.date(ANO, 2, 28))

    e = statement(scoped, ANO, 2)
    assert e.ends_on.day in (28, 29)
    assert e.total_expense == 1000


# --- La comparación ---------------------------------------------------------


@pytest.mark.django_db
def test_compara_contra_el_mes_anterior(scoped):
    _gasto(scoped, 3000, dt.date(ANO, 2, 10))
    _gasto(scoped, 5000, dt.date(ANO, 3, 10))

    linea = statement(scoped, ANO, 3).expenses[0]
    assert linea.amount == 5000
    assert linea.previous == 3000
    assert linea.change == 2000
    assert linea.change_pct == pytest.approx(2 / 3)


@pytest.mark.django_db
def test_de_enero_se_compara_contra_diciembre_del_ano_pasado(scoped):
    _gasto(scoped, 3000, dt.date(ANO - 1, 12, 10))
    _gasto(scoped, 5000, dt.date(ANO, 1, 10))

    e = statement(scoped, ANO, 1)
    assert e.previous_expense == 3000
    assert "iciembre" in e.previous_label


@pytest.mark.django_db
def test_el_ano_se_compara_contra_el_anterior(scoped):
    _gasto(scoped, 3000, dt.date(ANO - 1, 6, 10))
    _gasto(scoped, 5000, dt.date(ANO, 6, 10))

    e = statement(scoped, ANO)
    assert e.previous_expense == 3000
    assert e.previous_label == str(ANO - 1)


@pytest.mark.django_db
def test_una_categoria_nueva_se_marca_como_tal(scoped):
    """Vale la pena mirarla aunque sea pequeña: antes no existía."""
    _gasto(scoped, 3000, dt.date(ANO, 2, 10), categoria="Súper")
    _gasto(scoped, 3000, dt.date(ANO, 3, 10), categoria="Súper")
    _gasto(scoped, 400, dt.date(ANO, 3, 12), categoria="Gimnasio")

    nueva = next(x for x in statement(scoped, ANO, 3).expenses
                 if x.label == "Gimnasio")
    assert nueva.is_new


@pytest.mark.django_db
def test_lo_que_dejo_de_gastarse_sigue_saliendo(scoped):
    """Que algo desaparezca es tan informativo como que aparezca."""
    _gasto(scoped, 3000, dt.date(ANO, 2, 10), categoria="Gimnasio")
    _gasto(scoped, 500, dt.date(ANO, 3, 10), categoria="Súper")

    ido = next(x for x in statement(scoped, ANO, 3).expenses
               if x.label == "Gimnasio")
    assert ido.amount == 0
    assert ido.previous == 3000
    assert ido.change == -3000


@pytest.mark.django_db
def test_sin_periodo_anterior_no_se_calcula_un_porcentaje(scoped):
    _gasto(scoped, 5000, dt.date(ANO, 3, 10))

    assert statement(scoped, ANO, 3).expenses[0].change_pct is None


# --- Los traspasos no son ni ingreso ni gasto -------------------------------


@pytest.mark.django_db
def test_un_traspaso_no_aparece_en_el_estado(scoped):
    """No hay que filtrarlos: no tocan ninguna cuenta de ingreso ni de gasto."""
    from lares.core.forms import TransferForm

    banco = _cuenta(scoped, "Banco", Account.Type.ASSET)
    efectivo = _cuenta(scoped, "Efectivo", Account.Type.ASSET)
    _ingreso(scoped, 10000, dt.date(ANO, 3, 1))

    form = TransferForm({"date": dt.date(ANO, 3, 5), "amount": "4000",
                         "origin": str(banco.pk),
                         "destination": str(efectivo.pk)}, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    e = statement(scoped, ANO, 3)
    assert e.total_income == 10000
    assert e.total_expense == 0
    assert e.result == 10000


# --- Honestidad -------------------------------------------------------------


@pytest.mark.django_db
def test_un_periodo_en_curso_se_marca_como_parcial(scoped):
    """Si no, el mes en curso siempre parece un desastre frente al anterior."""
    assert statement(scoped, HOY.year, HOY.month).is_partial


@pytest.mark.django_db
def test_un_periodo_cerrado_no_se_marca(scoped):
    assert not statement(scoped, ANO - 1, 6).is_partial


# --- Pantalla ---------------------------------------------------------------


@pytest.mark.django_db
def test_la_pantalla_abre_por_mes_y_por_ano(sesion_admin, household):
    _gasto(household, 5000, dt.date(ANO, 3, 10))

    for url in ("/dinero/resultado/",
                f"/dinero/resultado/?ano={ANO}&mes=3",
                f"/dinero/resultado/?ano={ANO}&mes=todo"):
        assert sesion_admin.get(url).status_code == 200, url


@pytest.mark.django_db
def test_no_ofrece_avanzar_a_un_periodo_futuro(sesion_admin, household):
    contexto = sesion_admin.get("/dinero/resultado/").context

    assert contexto["siguiente"] is None
