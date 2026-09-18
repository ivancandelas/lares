"""Obligaciones que no cuelgan de un recurso: documentos y reglas propias."""

import datetime as dt

import pytest

from lares.core.models import Document, Obligation, ObligationRule
from lares.core.services import obligations

HOY = dt.date(2026, 9, 18)


@pytest.mark.django_db
def test_un_documento_que_vence_genera_su_renovacion(scoped):
    Document.objects.create(
        household=scoped, title="Pasaporte", doc_type="passport",
        expires_on=dt.date(2027, 5, 16),
    )
    obligations.materialize(scoped, HOY)

    o = Obligation.objects.get(source="core.document_expiry")
    assert o.title == "Renovar Pasaporte"
    assert o.due_on == dt.date(2027, 5, 16)
    # Un pasaporte exige cita previa: el primer aviso sale con meses de margen.
    assert min(o.remind_offsets) == -270


@pytest.mark.django_db
def test_un_documento_sin_vencimiento_no_genera_nada(scoped):
    Document.objects.create(household=scoped, title="Manual del boiler")
    obligations.materialize(scoped, HOY)
    assert Obligation.objects.filter(source="core.document_expiry").count() == 0


@pytest.mark.django_db
def test_una_regla_propia_se_materializa_como_cualquier_otra(scoped):
    ObligationRule.objects.create(
        household=scoped, key="colegiatura", label="Colegiatura",
        schedule={"monthly": {"day": 10}}, amount=4500,
    )
    obligations.materialize(scoped, HOY)

    creadas = Obligation.objects.filter(source="core.user_rule")
    assert creadas.count() == 2                 # la proxima y la siguiente
    assert creadas.first().amount == 4500


@pytest.mark.django_db
def test_una_regla_desactivada_deja_de_generar(scoped):
    rule = ObligationRule.objects.create(
        household=scoped, key="gym", label="Gimnasio",
        schedule={"monthly": {"day": 1}}, is_active=False,
    )
    obligations.materialize(scoped, HOY)
    assert Obligation.objects.filter(rule=rule).count() == 0
