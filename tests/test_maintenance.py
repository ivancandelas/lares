"""Mantenimiento: el plan avisa, el historial recuerda.

Las dos preguntas por las que existe el módulo: «¿quién arregló el boiler?» y
«¿cuánto llevo gastado en el coche?».
"""

import datetime as dt

import pytest
from django.contrib.contenttypes.models import ContentType

from lares.core.models import Obligation, Party
from lares.core.services import checks, obligations
from lares.modules.maintenance import services
from lares.modules.maintenance.models import MaintenancePlan, WorkOrder
from lares.modules.vehicles.models import Vehicle

HOY = dt.date.today()


@pytest.fixture
def mazda(scoped, me):
    return Vehicle.objects.create(household=scoped, name="Mazda CX-5",
                                  kind="vehicle", owner=me)


@pytest.fixture
def taller(scoped):
    return Party.objects.create(household=scoped, name="Taller del Valle",
                                kind=Party.Kind.ORGANIZATION)


def _plan(household, cosa, titulo="Afinación", meses=12, ultima=None, proveedor=None):
    return MaintenancePlan.objects.create(
        household=household, title=titulo,
        subject_type=ContentType.objects.get_for_model(cosa.__class__),
        subject_id=cosa.pk, basis=MaintenancePlan.Basis.TIME,
        every_months=meses, last_done_on=ultima, preferred_provider=proveedor,
        estimated_cost=4750,
    )


def _trabajo(household, cosa, titulo, cuando, proveedor=None, coste=None, plan=None):
    return WorkOrder.objects.create(
        household=household, title=titulo, done_on=cuando, provider=proveedor,
        cost=coste, plan=plan,
        subject_type=ContentType.objects.get_for_model(cosa.__class__),
        subject_id=cosa.pk,
    )


# --- El plan avisa ----------------------------------------------------------


@pytest.mark.django_db
def test_el_plan_genera_su_proximo_aviso(scoped, mazda, taller):
    _plan(scoped, mazda, ultima=HOY - dt.timedelta(days=300), proveedor=taller)
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.get(source="maintenance.plan")
    assert "Afinación" in aviso.title
    assert aviso.amount == 4750
    assert str(aviso.counterparty) == "Taller del Valle"


@pytest.mark.django_db
def test_un_plan_muy_atrasado_avisa_hoy_no_en_el_pasado(scoped, mazda):
    """Con fecha pasada quedaría escondido entre lo vencido antiguo."""
    _plan(scoped, mazda, ultima=HOY - dt.timedelta(days=900))
    obligations.materialize(scoped, HOY)

    assert Obligation.objects.get(source="maintenance.plan").due_on == HOY


@pytest.mark.django_db
def test_un_plan_pausado_deja_de_avisar(scoped, mazda):
    plan = _plan(scoped, mazda, ultima=HOY - dt.timedelta(days=300))
    plan.is_active = False
    plan.save()
    obligations.materialize(scoped, HOY)

    assert not Obligation.objects.filter(source="maintenance.plan").exists()


@pytest.mark.django_db
def test_registrar_el_trabajo_adelanta_el_plan(scoped, mazda, taller):
    """Si no, el aviso seguiría ahí después de haberlo hecho."""
    from lares.modules.maintenance.forms import WorkOrderForm

    plan = _plan(scoped, mazda, ultima=HOY - dt.timedelta(days=400))
    form = WorkOrderForm({
        "title": "Afinación hecha", "done_on": str(HOY), "subject": mazda.pk,
        "provider": taller.pk, "cost": "4750", "plan": plan.pk,
    }, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    plan.refresh_from_db()
    assert plan.last_done_on == HOY


# --- El historial recuerda --------------------------------------------------


@pytest.mark.django_db
def test_quien_lo_hizo_la_vez_pasada(scoped, mazda, taller):
    _trabajo(scoped, mazda, "Afinación", HOY - dt.timedelta(days=200), taller, 4750)
    _trabajo(scoped, mazda, "Balanceo", HOY - dt.timedelta(days=45), taller, 890)

    historial = services.history_for(mazda)
    assert [w.title for w in historial] == ["Balanceo", "Afinación"]   # lo último primero
    assert str(historial[0].provider) == "Taller del Valle"


@pytest.mark.django_db
def test_cuanto_llevo_gastado_en_esa_cosa(scoped, mazda, taller):
    _trabajo(scoped, mazda, "Afinación", HOY - dt.timedelta(days=200), taller, 4750)
    _trabajo(scoped, mazda, "Balanceo", HOY - dt.timedelta(days=45), taller, 890)

    assert services.spent_on(mazda) == 5640


@pytest.mark.django_db
def test_el_historial_de_una_cosa_no_incluye_el_de_otra(scoped, mazda, taller, me):
    otro = Vehicle.objects.create(household=scoped, name="Nissan", kind="vehicle",
                                  owner=me)
    _trabajo(scoped, mazda, "Afinación", HOY, taller, 4750)
    _trabajo(scoped, otro, "Frenos", HOY, taller, 2100)

    assert services.spent_on(mazda) == 4750
    assert services.spent_on(otro) == 2100


@pytest.mark.django_db
def test_cuanto_le_he_pagado_a_cada_proveedor(scoped, mazda, taller):
    plomero = Party.objects.create(household=scoped, name="Plomería Hernández",
                                   kind=Party.Kind.ORGANIZATION)
    _trabajo(scoped, mazda, "Afinación", HOY - dt.timedelta(days=200), taller, 4750)
    _trabajo(scoped, mazda, "Balanceo", HOY - dt.timedelta(days=45), taller, 890)
    _trabajo(scoped, mazda, "Fuga", HOY - dt.timedelta(days=10), plomero, 1250)

    resumen = {p["provider__name"]: p for p in services.providers(scoped)}
    assert resumen["Taller del Valle"]["trabajos"] == 2
    assert resumen["Taller del Valle"]["total"] == 5640
    assert resumen["Plomería Hernández"]["ultimo"] == HOY - dt.timedelta(days=10)


# --- Huecos -----------------------------------------------------------------


@pytest.mark.django_db
def test_avisa_de_lo_que_lleva_el_doble_de_tiempo_sin_hacerse(scoped, mazda):
    _plan(scoped, mazda, meses=12, ultima=HOY - dt.timedelta(days=800))

    claves = {f.check for f in checks.run_all(scoped)}
    assert "maintenance.overdue" in claves


@pytest.mark.django_db
def test_un_retraso_normal_no_genera_ruido(scoped, mazda):
    _plan(scoped, mazda, meses=12, ultima=HOY - dt.timedelta(days=400))

    claves = {f.check for f in checks.run_all(scoped)}
    assert "maintenance.overdue" not in claves


@pytest.mark.django_db
def test_avisa_de_trabajos_sin_saber_quien_los_hizo(scoped, mazda):
    _trabajo(scoped, mazda, "Algo", HOY, proveedor=None, coste=500)

    claves = {f.check for f in checks.run_all(scoped)}
    assert "maintenance.no_provider" in claves
