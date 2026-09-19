"""Presupuesto: previsto contra real.

Un tope mensual dice «no te pases este mes»; un presupuesto responde «¿voy como
pensaba?». Son preguntas distintas, pero **una sola cifra por categoría**:
llevar un tope mensual en una tabla y un previsto anual en otra era decir dos
veces lo mismo, y en cuanto una se ajusta y la otra no, las dos dejan de ser
fiables. Lo que varía es la cadencia, porque el súper y las vacaciones no se
gastan igual.

Lo demás que se prueba es lo que separa esto de una tabla: la proyección de
cierre —no la desviación del mes, que un mes malo no dice nada— y el gasto que
cae fuera de lo presupuestado, que es por donde se escapa el dinero.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Posting
from lares.core.services import checks
from lares.modules.finance.models_plan import Plan, PlanLine
from lares.modules.finance.services_plan import report, seed_from

HOY = dt.date.today()


def _plan(household, **kwargs):
    datos = dict(name=f"Presupuesto {HOY.year}", kind=Plan.Kind.ANNUAL,
                 year=HOY.year, currency="MXN")
    datos.update(kwargs)
    return Plan.objects.create(household=household, **datos)


def _categoria(household, nombre="Supermercado"):
    return Account.objects.create(household=household, name=nombre,
                                  type=Account.Type.EXPENSE)


def _linea(household, plan, cuenta, importe, cadencia=PlanLine.Cadence.TOTAL):
    return PlanLine.objects.create(household=household, plan=plan,
                                   account=cuenta, amount=Decimal(importe),
                                   cadence=cadencia)


def _gastar(household, cuenta, importe, cuando=None, dimension=None):
    banco, _ = Account.objects.get_or_create(
        household=household, name="Banco", defaults={"type": Account.Type.ASSET})
    entry = Entry.objects.create(household=household, description="Gasto",
                                 date=cuando or dt.date(HOY.year, 2, 10))
    Posting.objects.create(household=household, entry=entry, account=cuenta,
                           amount=Decimal(importe), currency="MXN",
                           dimension=dimension)
    Posting.objects.create(household=household, entry=entry, account=banco,
                           amount=-Decimal(importe), currency="MXN")


# --- Una sola cifra, dos cadencias ------------------------------------------


@pytest.mark.django_db
def test_lo_mensual_se_multiplica_por_el_periodo(scoped):
    """8.000 al mes son 96.000 en el año, y no hay que escribirlo dos veces."""
    plan = _plan(scoped)
    linea = _linea(scoped, plan, _categoria(scoped), 8000,
                   PlanLine.Cadence.MONTHLY)

    assert linea.months == 12
    assert linea.period_amount == 96000
    assert plan.planned == 96000


@pytest.mark.django_db
def test_lo_que_cae_de_golpe_no_se_multiplica(scoped):
    """Un tope mensual sobre las vacaciones no significaría nada."""
    plan = _plan(scoped)
    linea = _linea(scoped, plan, _categoria(scoped, "Vacaciones"), 40000)

    assert linea.period_amount == 40000


@pytest.mark.django_db
def test_las_dos_cadencias_suman_en_el_mismo_total(scoped):
    plan = _plan(scoped)
    _linea(scoped, plan, _categoria(scoped, "Súper"), 8000,
           PlanLine.Cadence.MONTHLY)
    _linea(scoped, plan, _categoria(scoped, "Vacaciones"), 40000)

    assert plan.planned == 96000 + 40000


@pytest.mark.django_db
def test_el_ritmo_del_mes_sale_del_mismo_presupuesto(scoped):
    """No hay tabla de topes: son las líneas con cadencia mensual."""
    from lares.modules.finance.services import budgets

    plan = _plan(scoped)
    cuenta = _categoria(scoped)
    _linea(scoped, plan, cuenta, 8000, PlanLine.Cadence.MONTHLY)
    _linea(scoped, plan, _categoria(scoped, "Vacaciones"), 40000)

    lineas = budgets(scoped)["lines"]
    assert len(lineas) == 1                    # la de golpe no frena un mes
    assert lineas[0].planned == 8000


# --- Previsto contra real ---------------------------------------------------


@pytest.mark.django_db
def test_lo_real_sale_del_libro(scoped):
    plan = _plan(scoped)
    cuenta = _categoria(scoped)
    _linea(scoped, plan, cuenta, 100000)
    _gastar(scoped, cuenta, 22750)

    linea = report(scoped, plan).lines[0]
    assert linea.actual == 22750
    assert linea.variance == -77250


@pytest.mark.django_db
def test_lo_de_otro_ejercicio_no_cuenta(scoped):
    plan = _plan(scoped)
    cuenta = _categoria(scoped)
    _linea(scoped, plan, cuenta, 100000)
    _gastar(scoped, cuenta, 50000, cuando=dt.date(HOY.year - 1, 6, 1))

    assert report(scoped, plan).lines[0].actual == 0


# --- La proyección de cierre ------------------------------------------------


@pytest.mark.django_db
def test_proyecta_el_cierre_con_el_periodo_corrido(scoped):
    """Lo que importa no es la desviación del mes: es a dónde vas a acabar."""
    plan = _plan(scoped, kind=Plan.Kind.PROJECT, year=None,
                 starts_on=HOY - dt.timedelta(days=50),
                 ends_on=HOY + dt.timedelta(days=50))
    cuenta = _categoria(scoped, "Obra")
    _linea(scoped, plan, cuenta, 120000)
    _gastar(scoped, cuenta, 80000, cuando=HOY - dt.timedelta(days=10),
            dimension=plan)

    linea = report(scoped, plan).lines[0]
    assert 0.45 < plan.elapsed < 0.55
    assert linea.projection > 140000            # 80.000 en la mitad del tiempo
    assert linea.is_drifting


@pytest.mark.django_db
def test_ir_al_ritmo_previsto_no_es_desviarse(scoped):
    plan = _plan(scoped, kind=Plan.Kind.PROJECT, year=None,
                 starts_on=HOY - dt.timedelta(days=50),
                 ends_on=HOY + dt.timedelta(days=50))
    cuenta = _categoria(scoped, "Obra")
    _linea(scoped, plan, cuenta, 120000)
    _gastar(scoped, cuenta, 60000, cuando=HOY - dt.timedelta(days=10),
            dimension=plan)

    assert not report(scoped, plan).lines[0].is_drifting


@pytest.mark.django_db
def test_un_periodo_que_no_ha_empezado_no_proyecta_nada(scoped):
    """Dividir entre casi cero escupiría una cifra absurda."""
    plan = _plan(scoped, kind=Plan.Kind.PROJECT, year=None,
                 starts_on=HOY + dt.timedelta(days=30),
                 ends_on=HOY + dt.timedelta(days=90))
    _linea(scoped, plan, _categoria(scoped, "Obra"), 120000)

    assert plan.elapsed == 0.0
    assert report(scoped, plan).lines[0].projection is None


@pytest.mark.django_db
def test_avisa_de_la_categoria_que_va_a_cerrar_pasada(scoped):
    plan = _plan(scoped, kind=Plan.Kind.PROJECT, year=None,
                 starts_on=HOY - dt.timedelta(days=50),
                 ends_on=HOY + dt.timedelta(days=50))
    cuenta = _categoria(scoped, "Obra")
    _linea(scoped, plan, cuenta, 120000)
    _gastar(scoped, cuenta, 90000, cuando=HOY - dt.timedelta(days=10),
            dimension=plan)

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "finance.plan_drift")
    assert "va a cerrar" in hallazgo.title
    assert "del periodo corrido" in hallazgo.detail


@pytest.mark.django_db
def test_sin_periodo_suficiente_no_se_avisa(scoped):
    """Con dos semanas corridas, cualquier proyección es ruido."""
    plan = _plan(scoped, kind=Plan.Kind.PROJECT, year=None,
                 starts_on=HOY - dt.timedelta(days=3),
                 ends_on=HOY + dt.timedelta(days=360))
    cuenta = _categoria(scoped, "Obra")
    _linea(scoped, plan, cuenta, 120000)
    _gastar(scoped, cuenta, 90000, cuando=HOY - dt.timedelta(days=1),
            dimension=plan)

    assert not [f for f in checks.run_all(scoped)
                if f.check == "finance.plan_drift"]


# --- Un proyecto solo cuenta lo suyo ----------------------------------------


@pytest.mark.django_db
def test_un_proyecto_solo_cuenta_lo_que_se_le_atribuyo(scoped):
    """Si no, la obra de la cocina se comería todo el gasto de casa del año."""
    obra = _plan(scoped, name="Cocina", kind=Plan.Kind.PROJECT, year=None,
                 starts_on=HOY - dt.timedelta(days=30),
                 ends_on=HOY + dt.timedelta(days=30))
    cuenta = _categoria(scoped, "Casa")
    _linea(scoped, obra, cuenta, 120000)

    _gastar(scoped, cuenta, 40000, cuando=HOY - dt.timedelta(days=5),
            dimension=obra)
    _gastar(scoped, cuenta, 15000, cuando=HOY - dt.timedelta(days=5))

    assert report(scoped, obra).lines[0].actual == 40000


# --- Lo que nadie presupuestó -----------------------------------------------


@pytest.mark.django_db
def test_el_gasto_fuera_del_presupuesto_se_lista(scoped):
    """Es donde se escapa el dinero de quien solo presupuesta lo que ya sabe."""
    plan = _plan(scoped)
    previsto = _categoria(scoped, "Súper")
    _linea(scoped, plan, previsto, 100000)
    _gastar(scoped, previsto, 10000)
    _gastar(scoped, _categoria(scoped, "Multas"), 4300)

    informe = report(scoped, plan)
    assert [x.account.name for x in informe.unplanned] == ["Multas"]
    assert informe.actual == 14300


@pytest.mark.django_db
def test_avisa_del_gasto_fuera_del_presupuesto(scoped):
    plan = _plan(scoped)
    _linea(scoped, plan, _categoria(scoped, "Súper"), 100000)
    _gastar(scoped, _categoria(scoped, "Multas"), 4300)

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "finance.plan_unplanned")
    assert "fuera del presupuesto" in hallazgo.title
    assert "Multas" in hallazgo.detail


@pytest.mark.django_db
def test_un_proyecto_no_reclama_gasto_ajeno(scoped):
    """Todo lo que no se le atribuyó le es ajeno por definición."""
    obra = _plan(scoped, name="Cocina", kind=Plan.Kind.PROJECT, year=None,
                 starts_on=HOY - dt.timedelta(days=30))
    _linea(scoped, obra, _categoria(scoped, "Casa"), 120000)
    _gastar(scoped, _categoria(scoped, "Multas"), 4300)

    assert report(scoped, obra).unplanned == []


# --- Partir de lo del año pasado --------------------------------------------


@pytest.mark.django_db
def test_se_puede_partir_de_lo_que_de_verdad_gastaste(scoped):
    """Planear desde cero es lo que hace que nadie repita el ejercicio."""
    _gastar(scoped, _categoria(scoped, "Súper"), 92000,
            cuando=dt.date(HOY.year - 1, 6, 1))
    _gastar(scoped, _categoria(scoped, "Mascotas"), 17000,
            cuando=dt.date(HOY.year - 1, 8, 1))
    plan = _plan(scoped)

    assert seed_from(scoped, plan, HOY.year - 1) == 2
    assert plan.planned == 92000 + 17000


@pytest.mark.django_db
def test_partir_dos_veces_no_duplica_categorias(scoped):
    _gastar(scoped, _categoria(scoped, "Súper"), 92000,
            cuando=dt.date(HOY.year - 1, 6, 1))
    plan = _plan(scoped)

    seed_from(scoped, plan, HOY.year - 1)
    assert seed_from(scoped, plan, HOY.year - 1) == 0
    assert plan.lines.count() == 1


@pytest.mark.django_db
def test_no_se_pisa_lo_que_ya_ajustaste(scoped):
    cuenta = _categoria(scoped, "Súper")
    _gastar(scoped, cuenta, 92000, cuando=dt.date(HOY.year - 1, 6, 1))
    plan = _plan(scoped)
    _linea(scoped, plan, cuenta, 60000)

    seed_from(scoped, plan, HOY.year - 1)
    assert plan.lines.get(account=cuenta).amount == 60000


# --- Pantallas --------------------------------------------------------------


@pytest.mark.django_db
def test_las_pantallas_de_presupuesto_abren(sesion_admin, household):
    plan = _plan(household)
    linea = _linea(household, plan, _categoria(household), 50000)

    for url in ("/dinero/presupuesto/", "/dinero/presupuesto/nuevo/",
                f"/dinero/presupuesto/{plan.pk}/",
                f"/dinero/presupuesto/{plan.pk}/editar/",
                f"/dinero/presupuesto/{plan.pk}/categoria/",
                f"/dinero/presupuesto/linea/{linea.pk}/"):
        assert sesion_admin.get(url).status_code == 200, url


@pytest.mark.django_db
def test_la_direccion_vieja_de_topes_sigue_llevando_a_algun_sitio(sesion_admin,
                                                                  household):
    """Llegar a un 404 tras meses usándola es peor que un salto."""
    respuesta = sesion_admin.get("/dinero/topes/")

    assert respuesta.status_code == 302
    assert respuesta["Location"] == "/dinero/presupuesto/"


@pytest.mark.django_db
def test_partir_del_ano_pasado_desde_la_pantalla(sesion_admin, household):
    _gastar(household, _categoria(household, "Súper"), 92000,
            cuando=dt.date(HOY.year - 1, 6, 1))
    plan = _plan(household)

    sesion_admin.get(f"/dinero/presupuesto/{plan.pk}/partir/")
    # `plan.lines` pasa por el manager con ámbito de hogar y esta prueba no
    # está dentro de uno: se cuenta sin ámbito a propósito.
    assert PlanLine.all_objects.filter(plan=plan).count() == 1


@pytest.mark.django_db
def test_una_categoria_no_entra_dos_veces_en_el_mismo_presupuesto(scoped):
    from lares.modules.finance.forms import PlanLineForm

    plan = _plan(scoped)
    cuenta = _categoria(scoped)
    _linea(scoped, plan, cuenta, 50000)

    form = PlanLineForm({"account": str(cuenta.pk), "amount": "30000",
                         "cadence": PlanLine.Cadence.TOTAL},
                        plan=plan, household=scoped)
    assert not form.is_valid()
    assert "ya está en el presupuesto" in str(form.errors["account"])
