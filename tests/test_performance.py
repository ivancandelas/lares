"""Que ninguna pantalla se dispare en consultas.

No es una prueba de velocidad: es una red de seguridad contra el N+1 que
aparece sin avisar al añadir un módulo, y contra una llamada que se llame a sí
misma sin darse cuenta.

Los topes son holgados a propósito. Si alguno salta, casi siempre es que falta
un `select_related` o que algo se está recalculando dentro de un bucle.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

TOPES = {
    "core:dashboard": 200,
    "core:holdings": 160,
    "core:documents": 30,
    "core:parties": 120,
    "finance:accounts": 90,
    "finance:spending": 60,
    "finance:health": 140,
    "finance:budgets": 40,
    "loans:list": 60,
    "subscriptions:list": 40,
}


@pytest.fixture
def poblado(sesion_admin, household):
    from django.core.management import call_command

    call_command("seed_demo", name=household.name, verbosity=0)
    return sesion_admin


@pytest.mark.django_db
@pytest.mark.parametrize("nombre,tope", TOPES.items())
def test_ninguna_pantalla_se_dispara_en_consultas(poblado, nombre, tope):
    with CaptureQueriesContext(connection) as capturadas:
        respuesta = poblado.get(reverse(nombre))

    assert respuesta.status_code == 200
    assert len(capturadas) < tope, (
        f"{nombre} hizo {len(capturadas)} consultas (tope {tope}). "
        "Suele ser un select_related que falta o algo recalculado en un bucle."
    )


@pytest.mark.django_db
def test_el_patrimonio_no_recorre_los_recursos_dos_veces(poblado):
    """La vista y el cálculo consolidado recorrían lo mismo por separado."""
    from lares.core.models import Household, Resource
    from lares.core.scoping import use_household

    hogar = Household.objects.order_by("created_at").first()
    with use_household(hogar):
        cuantos = Resource.objects.count()

    with CaptureQueriesContext(connection) as capturadas:
        poblado.get(reverse("core:holdings"))

    # Holgado: lo que se vigila es que no crezca con el cuadrado del inventario.
    assert len(capturadas) < cuantos * 8
