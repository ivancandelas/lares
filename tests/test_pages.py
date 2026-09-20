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


# --- Que un formulario pinte sus campos -------------------------------------

# Toda pantalla que use `core/form.html` y no pase por `LaresForm`. La
# plantilla recorre `form.groups`: un formulario sin esa propiedad se renderiza
# **vacío y sin error**, con un 200 impecable y ni un solo campo. Pasó con el
# gasto, el traspaso y el ingreso a la vez.
FORMULARIOS_SUELTOS = [
    "core:expense-new",
    "core:income-new",
    "core:transfer-new",
]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", FORMULARIOS_SUELTOS)
def test_un_formulario_suelto_pinta_sus_campos(sesion, url_name):
    respuesta = sesion.get(reverse(url_name))
    assert respuesta.status_code == 200

    form = respuesta.context["form"]
    html = respuesta.content.decode()
    assert form.fields, f"{url_name} no tiene campos"
    for nombre in form.fields:
        assert f'name="{nombre}"' in html, (
            f"{url_name}: el campo «{nombre}» no llegó al HTML. "
            "Casi siempre es un formulario sin `groups`, que la plantilla "
            "recorre en silencio."
        )


@pytest.mark.django_db
@pytest.mark.parametrize("kind", sorted(registry.resource_forms))
def test_todo_formulario_de_alta_pinta_sus_campos(sesion, kind):
    """El 200 no basta: una ficha en blanco también responde 200."""
    respuesta = sesion.get(reverse("core:resource-new", args=[kind]))
    form = respuesta.context["form"]
    html = respuesta.content.decode()

    assert form.fields, f"el alta de {kind} no tiene campos"
    faltan = [n for n in form.fields if f'name="{n}"' not in html]
    assert not faltan, f"alta de {kind}: campos que no se pintaron: {faltan}"


@pytest.mark.django_db
def test_todo_formulario_sabe_agruparse(sesion):
    """La garantía a nivel de código, no de pantalla.

    Si alguien escribe un `forms.Form` nuevo y lo sirve con `core/form.html`,
    esto lo caza aunque olvide añadir la URL a la lista de arriba.
    """
    import inspect

    from django import forms as django_forms

    from lares.core import forms as lares_forms

    sospechosos = [
        cls for _, cls in inspect.getmembers(lares_forms, inspect.isclass)
        if issubclass(cls, django_forms.BaseForm)
        and cls.__module__ == lares_forms.__name__
    ]
    assert sospechosos
    sin_groups = [c.__name__ for c in sospechosos if not hasattr(c, "groups")]
    assert not sin_groups, (
        f"Estos formularios se renderizarían vacíos: {sin_groups}. "
        "Heredan de `GroupedForm` o no los pinta `core/form.html`."
    )


@pytest.mark.django_db
def test_ninguna_pantalla_mete_html_en_el_titulo(sesion, household):
    """El `<title>` es texto: lo que se cuele ahí se lee en la pestaña.

    La ficha de recurso tenía el bloque `title` sin cerrar, así que se tragaba
    las previsualizaciones y las pestañas de los módulos: salían dentro del
    título *y* otra vez en la página, renderizadas dos veces. Desde fuera es un
    200 impecable.
    """
    import re

    from django.core.management import call_command

    from lares.core.models import Resource
    from lares.core.scoping import use_household

    call_command("seed_demo", name=household.name, verbosity=0)
    with use_household(household):
        recursos = list(Resource.objects.all())

    rutas = [reverse(item.url_name) for item in registry.nav_items]
    rutas += [reverse("core:resource-detail", args=[r.pk]) for r in recursos]

    for ruta in rutas:
        html = sesion.get(ruta).content.decode()
        titulo = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
        assert "<" not in titulo, f"{ruta}: hay marcado dentro del <title>"
        assert len(titulo) < 120, f"{ruta}: el título son {len(titulo)} caracteres"
