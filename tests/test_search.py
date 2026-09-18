"""La busqueda global encuentra lo que aportan los modulos sin conocerlos."""

import pytest

from lares.core.services.search import search
from lares.modules.vehicles.models import Vehicle


@pytest.mark.django_db
def test_encuentra_un_recurso_de_un_modulo(scoped, me):
    Vehicle.objects.create(
        household=scoped, name="Mazda CX-5", kind="vehicle", plates="JGT1234", owner=me
    )
    hits = search(scoped, "mazda")
    assert [h.title for h in hits] == ["Mazda CX-5"]
    assert hits[0].kind == "resource"


@pytest.mark.django_db
def test_ignora_consultas_demasiado_cortas(scoped):
    assert search(scoped, "a") == []
