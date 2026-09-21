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


@pytest.mark.django_db
def test_los_gestos_fisicos_solo_donde_significan_algo(sesion_admin, scoped):
    """«Prestar» una póliza no significa nada.

    El núcleo daba por hecho que todo recurso es una cosa que puedes tener en
    la mano, y ofrecía los mismos cuatro botones a una guitarra y a un seguro.
    No es solo ruido: ver «Prestar» en una póliza hace dudar de si el sistema
    entendió lo que estabas dando de alta.
    """
    from lares.modules.belongings.models import Belonging
    from lares.modules.insurance.models import Policy

    guitarra = Belonging.objects.create(household=scoped, kind="belonging",
                                        name="Guitarra")
    poliza = Policy.objects.create(household=scoped, kind="policy",
                                   name="Seguro del coche")

    de_la_guitarra = sesion_admin.get(f"/r/{guitarra.pk}/").content.decode()
    assert "Prestar" in de_la_guitarra
    assert "Sigo teniéndolo" in de_la_guitarra

    de_la_poliza = sesion_admin.get(f"/r/{poliza.pk}/").content.decode()
    assert "Prestar" not in de_la_poliza
    assert "Sigo teniéndolo" not in de_la_poliza


@pytest.mark.django_db
def test_cada_tipo_declara_que_gestos_admite():
    """Un tipo nuevo hereda «sí» a todo, que es la respuesta correcta para una
    cosa y la equivocada para un contrato. Esta lista deja constancia de lo
    decidido, para que cambiarlo sea deliberado."""
    import django.apps as apps

    from lares.core.models import Resource

    fisicos = {"belonging", "vehicle"}
    for modelo in apps.apps.get_models():
        if not (issubclass(modelo, Resource) and getattr(modelo, "resource_kind", "")):
            continue
        esperado = modelo.resource_kind in fisicos
        assert modelo.can_be_lent is esperado, modelo.resource_kind
        assert modelo.can_be_checked is esperado, modelo.resource_kind
