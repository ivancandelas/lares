"""Que todas las pantallas rendericen.

Esta prueba existe porque una plantilla con un `{% empty %}` mal puesto llegó a
producción: la lógica estaba probada y la página devolvía 500. Recorre todo lo
que el registro publica, así que un módulo nuevo queda cubierto sin escribir
nada.
"""

import pytest
from django.urls import reverse

from lares.core.registry import registry


@pytest.fixture
def sesion(client, django_user_model, household):
    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    client.force_login(user)
    return client


def _nav_urls():
    return [item.url_name for item in registry.nav_items]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", _nav_urls())
def test_toda_pantalla_del_menu_responde(sesion, url_name):
    respuesta = sesion.get(reverse(url_name))
    assert respuesta.status_code == 200, f"{url_name} devolvió {respuesta.status_code}"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", sorted(registry.resource_forms))
def test_todo_formulario_de_alta_responde(sesion, kind):
    respuesta = sesion.get(reverse("core:resource-new", args=[kind]))
    assert respuesta.status_code == 200, f"alta de {kind} devolvió {respuesta.status_code}"


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", [
    "core:dashboard", "core:holdings", "core:documents", "core:parties",
    "core:rules", "core:inbox", "core:connectors", "core:add", "core:onboarding",
    "core:search", "core:document-new", "core:party-new", "core:account-new",
    "core:expense-new", "core:rule-new", "core:location-new",
])
def test_las_pantallas_del_nucleo_responden(sesion, url_name):
    assert sesion.get(reverse(url_name)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("key", sorted(registry.connectors))
def test_todo_alta_de_conector_responde(sesion, key):
    assert sesion.get(reverse("core:connector-new", args=[key])).status_code == 200


@pytest.mark.django_db
def test_las_pantallas_tambien_responden_con_datos(sesion, household):
    """Una lista vacía y una con datos recorren ramas distintas de la plantilla."""
    from django.core.management import call_command

    call_command("seed_demo", name=household.name, verbosity=0)
    for item in registry.nav_items:
        respuesta = sesion.get(reverse(item.url_name))
        assert respuesta.status_code == 200, item.url_name


@pytest.mark.django_db
def test_toda_ficha_de_recurso_responde(sesion, household):
    from django.core.management import call_command

    from lares.core.models import Resource
    from lares.core.scoping import use_household

    # Se siembra sobre el hogar de la prueba, que es el que resuelve el
    # middleware: el mas antiguo.
    call_command("seed_demo", name=household.name, verbosity=0)
    with use_household(household):
        recursos = list(Resource.objects.all())

    assert recursos
    for recurso in recursos:
        respuesta = sesion.get(reverse("core:resource-detail", args=[recurso.pk]))
        assert respuesta.status_code == 200, f"{recurso.kind}: {recurso.name}"


@pytest.mark.django_db
def test_las_plantillas_no_dejan_comentarios_a_la_vista(sesion, household):
    """Un `{# #}` de varias líneas no es un comentario: Django lo imprime tal cual."""
    from django.core.management import call_command
    from django.urls import reverse

    call_command("seed_demo", name=household.name, verbosity=0)
    rutas = ["core:dashboard", "core:holdings", "core:inbox", "finance:spending"]
    for nombre in rutas:
        contenido = sesion.get(reverse(nombre)).content.decode()
        assert "{#" not in contenido, nombre
        assert "#}" not in contenido, nombre
        assert "{%" not in contenido, nombre


@pytest.mark.django_db
def test_la_pagina_carga_alpine(sesion, household):
    """Los desplegables del menú dependen de él; sin el script quedan muertos."""
    from django.urls import reverse

    contenido = sesion.get(reverse("core:dashboard")).content.decode()
    assert "alpine.min.js" in contenido
    assert 'x-data="{ open: null }"' in contenido


@pytest.mark.django_db
def test_el_menu_no_recorta_sus_desplegables(sesion, household):
    """`overflow-x-auto` en el nav crea un contexto de recorte.

    Los desplegables van posicionados en absoluto y se abren *fuera* del nav,
    así que con overflow se abren y no se ven. El síntoma es idéntico a que el
    JavaScript no funcione, y cuesta mucho de diagnosticar.
    """
    import re

    from django.urls import reverse

    contenido = sesion.get(reverse("core:dashboard")).content.decode()
    nav = re.search(r"<nav[^>]*>", contenido).group(0)
    assert "overflow-x-auto" not in nav
    assert "overflow-hidden" not in nav


@pytest.mark.django_db
def test_el_javascript_se_sirve_desde_la_propia_instalacion(sesion, household):
    """Un self-hosted cuyo menú muere sin internet no es self-hosted."""
    from django.urls import reverse

    contenido = sesion.get(reverse("core:dashboard")).content.decode()
    assert "unpkg.com" not in contenido
    assert "/static/vendor/alpine" in contenido
