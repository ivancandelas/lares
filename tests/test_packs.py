"""Packs de jurisdicción.

Una fecha que cambia por estado y por año no debería exigir un despliegue. Y al
revés: una regla que necesita leer el odómetro o la placa no cabe en un YAML sin
convertirse en código disfrazado.
"""

import datetime as dt

import pytest

from lares.core import packs
from lares.core.models import Obligation
from lares.core.services import obligations
from lares.modules.property.models import Property
from lares.modules.vehicles.models import Vehicle

HOY = dt.date(2026, 9, 18)

PACK = """
meta:
  id: prueba
  country: MX
  subdivision: MX-JAL
rules:
  - id: refrendo
    label: "Refrendo {year}, {subject}"
    applies_to: vehicle
    schedule: {yearly: {month: 3, day: 31}}
    remind: [-60, -30]
    severity: high
  - id: predial
    label: "Predial {year}"
    applies_to: property
    only_if: {is_mine: true}
    amount_field: predial_amount
    schedule: {yearly: {month: 1, day: 31}}
"""


@pytest.fixture
def pack_dir(tmp_path):
    (tmp_path / "prueba.yaml").write_text(PACK, encoding="utf-8")
    return tmp_path


def test_lee_las_reglas_de_un_pack(pack_dir):
    reglas = packs.load(pack_dir)
    assert {r.id for r in reglas} == {"refrendo", "predial"}
    assert reglas[0].subdivision == "MX-JAL"


def test_un_yaml_roto_no_tumba_a_los_demas(tmp_path):
    (tmp_path / "bueno.yaml").write_text(PACK, encoding="utf-8")
    (tmp_path / "roto.yaml").write_text("esto: [no cierra", encoding="utf-8")

    assert len(packs.load(tmp_path)) == 2


def test_una_regla_incompleta_se_salta_sin_reventar(tmp_path):
    (tmp_path / "medio.yaml").write_text(
        "meta: {id: x}\nrules:\n  - id: sin_label\n    applies_to: vehicle\n",
        encoding="utf-8",
    )
    assert packs.load(tmp_path) == []


@pytest.mark.django_db
def test_el_pack_del_estado_correcto_aplica(scoped, me, pack_dir):
    scoped.subdivision = "MX-JAL"
    scoped.save()
    coche = Vehicle.objects.create(household=scoped, name="Mazda", kind="vehicle",
                                   owner=me)
    regla = packs.load(pack_dir)[0]
    spec = packs.PackProvider("vehicle", [regla]).generate(coche, HOY)[0]

    assert spec.title == "Refrendo 2027, Mazda"
    assert spec.due_on == dt.date(2027, 3, 31)
    assert spec.remind_offsets == (-60, -30)


@pytest.mark.django_db
def test_el_pack_de_otro_estado_no_aplica(scoped, me, pack_dir):
    scoped.subdivision = "MX-NLE"          # Nuevo León
    scoped.save()
    coche = Vehicle.objects.create(household=scoped, name="Mazda", kind="vehicle",
                                   owner=me)

    regla = packs.load(pack_dir)[0]
    assert packs.PackProvider("vehicle", [regla]).generate(coche, HOY) == []


@pytest.mark.django_db
def test_only_if_filtra_por_un_atributo_del_recurso(scoped, me, pack_dir):
    """El predial lo paga el dueño; la casa que rentas no lo genera."""
    scoped.subdivision = "MX-JAL"
    scoped.save()
    mia = Property.objects.create(
        household=scoped, name="Mi departamento", kind="property",
        tenure=Property.Tenure.OWNED, predial_amount=4800, owner=me,
    )
    rentada = Property.objects.create(
        household=scoped, name="Donde vivo", kind="property",
        tenure=Property.Tenure.RENTED, owner=me,
    )
    regla = packs.load(pack_dir)[1]
    provider = packs.PackProvider("property", [regla])

    assert provider.generate(mia, HOY)[0].amount == 4800
    assert provider.generate(rentada, HOY) == []


@pytest.mark.django_db
def test_el_pack_real_genera_refrendo_y_predial(scoped, me):
    """Contra los packs de verdad del repositorio, no contra un fixture."""
    scoped.country, scoped.subdivision = "MX", "MX-JAL"
    scoped.save()
    Vehicle.objects.create(household=scoped, name="Mazda", kind="vehicle",
                           plates="JGT1234", owner=me)
    Property.objects.create(household=scoped, name="Departamento", kind="property",
                            tenure=Property.Tenure.OWNED, predial_amount=4800,
                            owner=me)
    obligations.materialize(scoped, HOY)

    titulos = list(Obligation.objects.filter(source__startswith="packs.")
                   .values_list("title", flat=True))
    assert any(t.startswith("Refrendo") for t in titulos)
    assert any(t.startswith("Predial") for t in titulos)
