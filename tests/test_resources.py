"""La ficha genérica de cualquier cosa.

Un módulo nuevo tiene ficha sin escribir plantilla: los datos se derivan del
modelo. Eso ahorra mucho y a cambio obliga a acertar en cómo se formatea cada
tipo de dato, porque nadie va a revisarlo campo por campo.
"""

import pytest

@pytest.mark.django_db
def test_un_ano_no_se_muestra_con_separador_de_miles(scoped, me):
    """«2,022» no es un año. Un año es un identificador, no una cantidad."""
    from lares.modules.vehicles.models import Vehicle

    coche = Vehicle.objects.create(household=scoped, name="Mazda",
                                   kind="vehicle", plates="AAA111",
                                   year=2022, owner=me)
    datos = dict(coche.facts())

    assert datos["Año"] == "2022"


@pytest.mark.django_db
def test_un_kilometraje_si_es_una_cantidad(scoped, me):
    """El filtro por nombre no puede tragarse los números de verdad."""
    from lares.modules.vehicles.models import Vehicle

    coche = Vehicle.objects.create(household=scoped, name="Mazda",
                                   kind="vehicle", plates="AAA111",
                                   year=2022, odometer_km=38400, owner=me)
    datos = dict(coche.facts())

    assert datos["Kilometraje"] == 38400
