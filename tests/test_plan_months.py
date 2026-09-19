"""Presupuesto mes a mes.

Diciembre no cuesta lo que marzo, y agosto lleva la inscripción. Pero obligar a
capturar doce cifras por categoría es lo que hace que nadie vuelva a tocar el
presupuesto después de la primera vez.

Por eso el importe sigue siendo **uno** y solo se guardan los meses que
difieren. Si una categoría vale igual todo el año, esta tabla no tiene ni una
fila para ella.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Posting
from lares.modules.finance.forms import MonthlyAmountsForm
from lares.modules.finance.models_plan import Plan, PlanLine, PlanLineMonth
from lares.modules.finance.services import budgets

HOY = dt.date.today()


def _linea(household, importe=8000, cadencia=PlanLine.Cadence.MONTHLY):
    plan = Plan.objects.create(household=household, name=f"Plan {HOY.year}",
                               kind=Plan.Kind.ANNUAL, year=HOY.year)
    cuenta = Account.objects.create(household=household, name="Súper",
                                    type=Account.Type.EXPENSE)
    return PlanLine.objects.create(household=household, plan=plan,
                                   account=cuenta, amount=Decimal(importe),
                                   cadence=cadencia)


def _capturar(household, linea, meses=None):
    """Los doce meses; los que no se digan van con el importe normal."""
    datos = {f"mes_{n}": str(linea.amount) for n in range(1, 13)}
    datos.update({f"mes_{n}": str(v) for n, v in (meses or {}).items()})
    form = MonthlyAmountsForm(datos, line=linea, household=household)
    assert form.is_valid(), form.errors
    form.save()
    linea.refresh_from_db()
    return linea


# --- Solo se guardan las excepciones ----------------------------------------


@pytest.mark.django_db
def test_sin_excepciones_todos_los_meses_valen_lo_mismo(scoped):
    linea = _linea(scoped)

    assert linea.overrides == {}
    assert linea.amount_for(3) == 8000
    assert linea.amount_for(12) == 8000


@pytest.mark.django_db
def test_se_puede_decir_que_diciembre_cuesta_mas(scoped):
    linea = _capturar(scoped, _linea(scoped), {12: 14000})

    assert linea.amount_for(12) == 14000
    assert linea.amount_for(11) == 8000


@pytest.mark.django_db
def test_poner_el_mismo_numero_doce_veces_no_guarda_nada(scoped):
    """Si no, cambiar el importe normal dejaría doce copias del viejo."""
    linea = _capturar(scoped, _linea(scoped))

    assert PlanLineMonth.objects.count() == 0
    assert linea.overrides == {}


@pytest.mark.django_db
def test_igualar_un_mes_al_normal_borra_la_excepcion(scoped):
    linea = _capturar(scoped, _linea(scoped), {12: 14000})
    assert linea.overrides

    linea = _capturar(scoped, linea)
    assert linea.overrides == {}


@pytest.mark.django_db
def test_un_mes_vacio_vuelve_al_importe_normal(scoped):
    linea = _capturar(scoped, _linea(scoped), {12: 14000})

    datos = {f"mes_{n}": "8000" for n in range(1, 13)}
    datos["mes_12"] = ""
    form = MonthlyAmountsForm(datos, line=linea, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    linea.refresh_from_db()
    assert linea.amount_for(12) == 8000


@pytest.mark.django_db
def test_cambiar_una_excepcion_no_crea_otra(scoped):
    linea = _capturar(scoped, _linea(scoped), {12: 14000})
    linea = _capturar(scoped, linea, {12: 16000})

    assert PlanLineMonth.objects.filter(line=linea).count() == 1
    assert linea.amount_for(12) == 16000


# --- Lo que cambia por tener meses distintos --------------------------------


@pytest.mark.django_db
def test_el_total_del_ano_suma_cada_mes_por_su_cuenta(scoped):
    linea = _capturar(scoped, _linea(scoped), {8: 11000, 12: 14000})

    # Diez meses a 8.000, uno a 11.000 y otro a 14.000.
    assert linea.period_amount == 10 * 8000 + 11000 + 14000


@pytest.mark.django_db
def test_el_tope_del_mes_corriente_usa_el_de_ese_mes(scoped):
    """De nada sirve capturar diciembre si en diciembre se avisa con 8.000."""
    linea = _capturar(scoped, _linea(scoped), {HOY.month: 20000})

    fila = budgets(scoped)["lines"][0]
    assert fila.planned == 20000


@pytest.mark.django_db
def test_un_gasto_se_mide_contra_el_tope_de_su_mes(scoped):
    linea = _capturar(scoped, _linea(scoped), {HOY.month: 3000})
    banco = Account.objects.create(household=scoped, name="Banco",
                                   type=Account.Type.ASSET)
    entry = Entry.objects.create(household=scoped, date=HOY.replace(day=2),
                                 description="Despensa")
    Posting.objects.create(household=scoped, entry=entry,
                           account=linea.account, amount=Decimal("4000"))
    Posting.objects.create(household=scoped, entry=entry, account=banco,
                           amount=Decimal("-4000"))

    fila = budgets(scoped)["lines"][0]
    assert fila.over
    assert fila.overspent == 1000


# --- Lo que no aplica -------------------------------------------------------


@pytest.mark.django_db
def test_una_categoria_de_golpe_no_tiene_meses(scoped):
    """«40.000 de vacaciones» no se reparte en doce: cae cuando cae."""
    linea = _linea(scoped, 40000, PlanLine.Cadence.TOTAL)

    assert linea.amount_for(3) == 40000
    assert linea.period_amount == 40000


@pytest.mark.django_db
def test_la_pantalla_rechaza_una_categoria_de_golpe(sesion_admin, household):
    linea = _linea(household, 40000, PlanLine.Cadence.TOTAL)
    respuesta = sesion_admin.get(
        f"/dinero/presupuesto/linea/{linea.pk}/meses/")

    assert respuesta.status_code == 302


# --- Pantalla ---------------------------------------------------------------


@pytest.mark.django_db
def test_la_pantalla_precarga_los_doce_con_el_importe_normal(sesion_admin,
                                                              household):
    linea = _linea(household)
    respuesta = sesion_admin.get(
        f"/dinero/presupuesto/linea/{linea.pk}/meses/")
    form = respuesta.context["form"]

    assert respuesta.status_code == 200
    assert len(form.fields) == 12
    assert all(form.fields[f"mes_{n}"].initial == 8000 for n in range(1, 13))


@pytest.mark.django_db
def test_la_pantalla_muestra_lo_ya_capturado(sesion_admin, household):
    linea = _capturar(household, _linea(household), {12: 14000})
    form = sesion_admin.get(
        f"/dinero/presupuesto/linea/{linea.pk}/meses/").context["form"]

    assert form.fields["mes_12"].initial == 14000
    assert form.fields["mes_11"].initial == 8000


@pytest.mark.django_db
def test_los_doce_campos_llegan_al_html(sesion_admin, household):
    linea = _linea(household)
    respuesta = sesion_admin.get(
        f"/dinero/presupuesto/linea/{linea.pk}/meses/")
    html = respuesta.content.decode()

    for n in range(1, 13):
        assert f'name="mes_{n}"' in html, n
