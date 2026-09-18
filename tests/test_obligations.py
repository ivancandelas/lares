"""El motor de obligaciones debe poder correr N veces sin duplicar nada.

Es la propiedad que hace que el usuario confie en los avisos. Si se duplican,
deja de leerlos y el producto muere.
"""

import datetime as dt

import pytest

from lares.core.models import Obligation, Reminder
from lares.core.services import checks, obligations
from lares.modules.vehicles.models import Vehicle

HOY = dt.date(2026, 9, 18)


@pytest.fixture
def mazda(scoped, me):
    return Vehicle.objects.create(
        household=scoped, name="Mazda CX-5", kind="vehicle",
        make="Mazda", model="CX-5", year=2022, plates="JGT1234",
        odometer_km=38400, avg_km_per_month=900,
        service_interval_km=10000, last_service_km=30000, owner=me,
    )


@pytest.mark.django_db
def test_genera_obligaciones_del_modulo(scoped, mazda):
    """El módulo aporta lo que depende del vehículo; el pack, lo que depende de la ley."""
    obligations.materialize(scoped, HOY)
    fuentes = set(Obligation.objects.values_list("source", flat=True))

    # De la placa y del odómetro: solo el módulo sabe leerlos.
    assert {"vehicles.verificacion", "vehicles.service"} <= fuentes
    # Del pack de jurisdicción: una fecha fija al año.
    assert "packs.vehicle" in fuentes
    assert Obligation.objects.filter(title__startswith="Refrendo").exists()


@pytest.mark.django_db
def test_materializar_es_idempotente(scoped, mazda):
    obligations.materialize(scoped, HOY)
    antes = Obligation.objects.count(), Reminder.objects.count()

    for _ in range(3):
        obligations.materialize(scoped, HOY)

    assert (Obligation.objects.count(), Reminder.objects.count()) == antes


@pytest.mark.django_db
def test_toda_obligacion_futura_genera_recordatorios(scoped, mazda):
    obligations.materialize(scoped, HOY)
    for obligation in Obligation.objects.all():
        assert obligation.reminders.count() == len(obligation.remind_offsets)


@pytest.mark.django_db
def test_detecta_vehiculo_sin_poliza(scoped, mazda):
    findings = checks.run_all(scoped)
    claves = {f.check for f in findings}
    assert "vehicles.no_policy" in claves
    assert findings[0].severity == "critical"   # lo mas grave va primero
