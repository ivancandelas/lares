"""Seguros.

Una póliza no "pertenece" a un coche: lo asegura, y esa arista tiene vigencia
propia. Es lo que permite responder qué estaba cubierto el día del siniestro.
"""

import datetime as dt

import pytest
from django.contrib.contenttypes.models import ContentType

from lares.core.models import Link, Obligation, Party
from lares.core.services import checks, obligations
from lares.modules.insurance.models import Policy
from lares.modules.vehicles.models import Vehicle

HOY = dt.date.today()


@pytest.fixture
def mazda(scoped, me):
    return Vehicle.objects.create(
        household=scoped, name="Mazda CX-5", kind="vehicle", plates="JGT1234",
        owner=me, current_value=410000,
    )


def _asegurar(household, policy, recurso, desde=None, hasta=None):
    return Link.objects.create(
        household=household,
        source_type=ContentType.objects.get_for_model(Policy), source_id=policy.pk,
        role="insures",
        target_type=ContentType.objects.get_for_model(recurso.__class__),
        target_id=recurso.pk,
        valid_from=desde or policy.starts_on, valid_to=hasta or policy.ends_on,
    )


@pytest.fixture
def poliza(scoped, mazda):
    gnp = Party.objects.create(household=scoped, name="GNP",
                               kind=Party.Kind.ORGANIZATION)
    policy = Policy.objects.create(
        household=scoped, name="Seguro del Mazda", kind="policy",
        branch=Policy.Branch.VEHICLE, insurer=gnp, policy_number="GNP-4471",
        coverage_amount=410000, premium=18500,
        starts_on=HOY - dt.timedelta(days=330), ends_on=HOY + dt.timedelta(days=35),
        currency="MXN",
    )
    _asegurar(scoped, policy, mazda)
    return policy


# --- El grafo ---------------------------------------------------------------


@pytest.mark.django_db
def test_la_poliza_sabe_que_cubre(scoped, poliza, mazda):
    assert [r.name for r in poliza.insured_resources()] == ["Mazda CX-5"]


@pytest.mark.django_db
def test_asegurar_resuelve_el_hueco_que_avisaba_otro_modulo(scoped, poliza, mazda):
    """El módulo de vehículos no conoce al de seguros: se entienden por el grafo."""
    claves = {f.check for f in checks.run_all(scoped)}
    assert "vehicles.no_policy" not in claves


@pytest.mark.django_db
def test_sin_poliza_el_aviso_vuelve(scoped, mazda):
    claves = {f.check for f in checks.run_all(scoped)}
    assert "vehicles.no_policy" in claves


@pytest.mark.django_db
def test_se_puede_saber_que_cubria_la_poliza_anterior(scoped, mazda):
    """La pregunta que una clave foránea no puede responder."""
    anterior = Policy.objects.create(
        household=scoped, name="Póliza 2025", kind="policy",
        starts_on=dt.date(2025, 1, 1), ends_on=dt.date(2025, 12, 31),
        coverage_amount=380000,
    )
    _asegurar(scoped, anterior, mazda)
    vigente = Policy.objects.create(
        household=scoped, name="Póliza 2026", kind="policy",
        starts_on=dt.date(2026, 1, 1), ends_on=dt.date(2026, 12, 31),
        coverage_amount=410000,
    )
    _asegurar(scoped, vigente, mazda)

    el_dia_del_choque = dt.date(2025, 6, 15)
    vigentes = Link.objects.filter(role="insures").valid_on(el_dia_del_choque)
    assert [link.source.name for link in vigentes] == ["Póliza 2025"]


# --- Obligaciones -----------------------------------------------------------


@pytest.mark.django_db
def test_la_renovacion_avisa_con_mes_y_medio(scoped, poliza):
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.get(source="insurance.renewal")
    assert aviso.due_on == poliza.ends_on
    assert aviso.severity == "critical"
    # Comparar otras opciones lleva semanas.
    assert min(aviso.remind_offsets) == -45
    assert str(aviso.counterparty) == "GNP"


@pytest.mark.django_db
def test_la_prima_anual_no_duplica_el_aviso_de_renovacion(scoped, poliza):
    obligations.materialize(scoped, HOY)
    assert not Obligation.objects.filter(source="insurance.premium").exists()


@pytest.mark.django_db
def test_una_prima_fraccionada_si_genera_sus_pagos(scoped, poliza):
    poliza.premium_cycle = Policy.Cycle.MONTHLY
    poliza.premium_day = 10
    poliza.save()
    obligations.materialize(scoped, HOY)

    assert Obligation.objects.filter(source="insurance.premium").count() == 2


# --- Huecos de cobertura ----------------------------------------------------


@pytest.mark.django_db
def test_avisa_si_la_suma_asegurada_se_queda_corta(scoped, poliza, mazda):
    mazda.current_value = 700000        # subió de valor, la póliza no
    mazda.save()

    hallazgos = [f for f in checks.run_all(scoped) if f.check == "insurance.underinsured"]
    assert hallazgos
    assert "vale más de lo que cubre" in hallazgos[0].title


@pytest.mark.django_db
def test_una_poliza_que_no_cubre_nada_es_inservible(scoped):
    Policy.objects.create(household=scoped, name="Póliza suelta", kind="policy")

    claves = {f.check for f in checks.run_all(scoped)}
    assert "insurance.covers_nothing" in claves


@pytest.mark.django_db
def test_una_poliza_vencida_se_marca_como_critica(scoped, mazda):
    vencida = Policy.objects.create(
        household=scoped, name="Póliza vieja", kind="policy",
        ends_on=HOY - dt.timedelta(days=5),
    )
    _asegurar(scoped, vencida, mazda)

    hallazgos = [f for f in checks.run_all(scoped) if f.check == "insurance.expired"]
    assert hallazgos and hallazgos[0].severity == "critical"


@pytest.mark.django_db
def test_una_poliza_no_es_patrimonio(scoped, poliza):
    assert not poliza.counts_as_asset


# --- Formulario -------------------------------------------------------------


@pytest.mark.django_db
def test_el_alta_ata_la_poliza_a_lo_que_cubre(scoped, mazda):
    from lares.modules.insurance.forms import PolicyForm

    form = PolicyForm({
        "name": "Seguro nuevo", "branch": "vehicle", "premium_cycle": "yearly",
        "status": "active", "covers": [mazda.pk],
        "starts_on": "2026-01-01", "ends_on": "2026-12-31",
    }, household=scoped)
    assert form.is_valid(), form.errors
    policy = form.save()

    assert [r.name for r in policy.insured_resources()] == ["Mazda CX-5"]


@pytest.mark.django_db
def test_quitar_algo_de_la_cobertura_borra_la_arista(scoped, poliza, mazda):
    from lares.modules.insurance.forms import PolicyForm

    form = PolicyForm({
        "name": poliza.name, "branch": poliza.branch, "premium_cycle": "yearly",
        "status": "active", "covers": [],
    }, instance=poliza, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    assert not poliza.insured_resources().exists()
