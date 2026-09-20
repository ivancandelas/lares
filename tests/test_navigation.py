"""Que a cada pantalla se pueda llegar sin teclear la dirección.

Esta prueba existe porque pasó tres veces: `/hogar/`, `/hogar/datos/` y
`/dinero/importar/` funcionaban perfectamente y no había forma de llegar a
ellas. Una pantalla a la que no se llega es una pantalla que no existe, y no
falla ninguna prueba: responde 200 y no la abre nadie.

Se rastrea el sitio como lo haría una persona —desde el tablero, siguiendo
enlaces y formularios— y se compara con todas las rutas que son un **destino**
(las que no llevan parámetros; las que cuelgan de una ficha se alcanzan desde
ella). Lo que no se alcance tiene que estar en `SIN_PUERTA` con su motivo.
"""

import re

import pytest
from django.urls import NoReverseMatch, Resolver404, get_resolver, resolve, reverse

# Rutas que a propósito no se enlazan desde ninguna pantalla. Cada una con su
# razón: si la lista crece sin motivo, la prueba deja de servir.
SIN_PUERTA = {
    "core:login": "se llega sin sesión, y el menú no existe todavía",
    "core:service-worker": "lo pide el navegador, no una persona",
    "core:inbox-share": "destino de «compartir» del sistema operativo; va en el manifest",
    "core:succession-here": "«Sigo aquí» solo aparece cuando hay un acceso abierto",
    "finance:import-confirm": "segundo paso del importador; se llega tras subir el archivo",
    "finance:budgets": "redirección de compatibilidad: los topes se fundieron en el presupuesto",
}

# El admin de Django es andamio y tiene su propia navegación.
FUERA = ("admin:",)


def _destinos() -> dict:
    """Las rutas que son un destino: las que se pueden pedir sin parámetros."""
    resolver = get_resolver()
    nombres = set()
    for espacio, (_, sub) in resolver.namespace_dict.items():
        nombres |= {f"{espacio}:{n}" for n in sub.reverse_dict if isinstance(n, str)}

    salida = {}
    for nombre in sorted(nombres):
        if nombre.startswith(FUERA) or ":api-" in nombre:
            continue
        try:
            salida[nombre] = reverse(nombre)
        except NoReverseMatch:
            continue          # lleva parámetros: cuelga de otra pantalla
    return salida


def _rastrea(client, inicio="/") -> set:
    """Todo lo que se alcanza siguiendo enlaces y formularios desde el tablero."""
    vistos, cola, alcanzadas = set(), [inicio], set()
    while cola:
        ruta = cola.pop()
        if ruta in vistos:
            continue
        vistos.add(ruta)
        try:
            alcanzadas.add(resolve(ruta).view_name)
        except Resolver404:
            continue

        respuesta = client.get(ruta)
        if respuesta.status_code != 200:
            continue
        if "html" not in respuesta.get("Content-Type", ""):
            continue
        for href in re.findall(r'(?:href|action)="(/[^"#?]*)',
                               respuesta.content.decode()):
            if href not in vistos:
                cola.append(href)
    return alcanzadas


@pytest.fixture
def sesion(client, django_user_model, household):
    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_a_toda_pantalla_se_llega_navegando(sesion, household):
    from django.core.management import call_command

    # Con datos: media navegación solo aparece cuando hay algo que enseñar.
    call_command("seed_demo", name=household.name, verbosity=0)

    destinos = _destinos()
    alcanzadas = _rastrea(sesion)

    huerfanas = sorted(n for n in destinos
                       if n not in alcanzadas and n not in SIN_PUERTA)

    assert not huerfanas, (
        "Pantallas a las que no se llega navegando: "
        + ", ".join(f"{n} ({destinos[n]})" for n in huerfanas)
        + ". Enlázalas desde el menú o desde la pantalla que las use; si de "
          "verdad no llevan puerta, añádelas a SIN_PUERTA con su motivo."
    )


@pytest.mark.django_db
def test_lo_que_dice_no_tener_puerta_sigue_existiendo(sesion):
    """Una excepción que sobra envejece en silencio y tapa la siguiente."""
    destinos = _destinos()

    sobran = sorted(n for n in SIN_PUERTA if n not in destinos)

    assert not sobran, f"Ya no existen, quítalas de SIN_PUERTA: {sobran}"
