"""Pruebas con navegador de verdad.

Existen porque tres fallos seguidos del menú pasaron las 200 pruebas anteriores
sin que ninguna se enterara:

  1. el <script> de Alpine desapareció en un rediseño
  2. `overflow-x-auto` en el <nav> recortaba los desplegables
  3. cada desplegable tenía su `@click.outside`, y pulsar uno era un clic
     "fuera" de los otros dos, que cerraban el menú en el mismo instante

Ninguno se ve desde Django: el HTML era correcto en los tres casos. Sin un
navegador que pulse de verdad, no hay forma de saberlo.
"""

import shutil

import pytest

CHROME = shutil.which("google-chrome") or shutil.which("chromium")

pytestmark = [
    pytest.mark.skipif(CHROME is None, reason="no hay Chrome en el sistema"),
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture
def page(live_server, django_user_model):
    """Navegador autenticado, sin pasar por el formulario de acceso."""
    playwright = pytest.importorskip("playwright.sync_api")

    from django.conf import settings
    from django.contrib.sessions.backends.db import SessionStore

    from lares.core.models import Household

    Household.objects.get_or_create(slug="casa", defaults={"name": "Casa"})
    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    sesion = SessionStore()
    sesion["_auth_user_id"] = str(user.pk)
    sesion["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    sesion["_auth_user_hash"] = user.get_session_auth_hash()
    sesion.create()

    with playwright.sync_playwright() as p:
        navegador = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = navegador.new_context(viewport={"width": 1100, "height": 800})
        ctx.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME, "value": sesion.session_key,
            "domain": "localhost", "path": "/",
        }])
        pagina = ctx.new_page()
        pagina.goto(live_server.url.replace("127.0.0.1", "localhost"),
                    wait_until="networkidle")
        yield pagina
        navegador.close()


def test_alpine_esta_disponible(page):
    assert page.evaluate("typeof window.Alpine !== 'undefined'")


@pytest.mark.parametrize("grupo,etiqueta", [
    ("holdings", "Patrimonio"),
    ("money", "Dinero"),
    ("more", "Más"),
])
def test_cada_desplegable_del_menu_se_abre(page, grupo, etiqueta):
    menu = page.locator(f"nav div[x-show*={grupo}]")
    assert not menu.is_visible()

    page.locator("nav button", has_text=etiqueta).click()
    page.wait_for_timeout(250)

    assert menu.is_visible(), f"«{etiqueta}» no se abrió"
    caja = menu.bounding_box()
    # Si algún ancestro lo recorta, el alto sale en cero aunque «esté visible».
    assert caja["height"] > 50, f"«{etiqueta}» se abrió pero está recortado"


def test_abrir_uno_cierra_el_anterior(page):
    page.locator("nav button", has_text="Patrimonio").click()
    page.wait_for_timeout(200)
    page.locator("nav button", has_text="Dinero").click()
    page.wait_for_timeout(200)

    assert not page.locator("nav div[x-show*=holdings]").is_visible()
    assert page.locator("nav div[x-show*=money]").is_visible()


def test_volver_a_pulsar_lo_cierra(page):
    boton = page.locator("nav button", has_text="Patrimonio")
    boton.click()
    page.wait_for_timeout(200)
    boton.click()
    page.wait_for_timeout(200)

    assert not page.locator("nav div[x-show*=holdings]").is_visible()


def test_pulsar_fuera_lo_cierra(page):
    page.locator("nav button", has_text="Patrimonio").click()
    page.wait_for_timeout(200)
    page.locator("main").click(position={"x": 10, "y": 10})
    page.wait_for_timeout(200)

    assert not page.locator("nav div[x-show*=holdings]").is_visible()


def test_se_puede_navegar_desde_el_desplegable(page):
    page.locator("nav button", has_text="Patrimonio").click()
    page.wait_for_timeout(200)
    page.locator("nav a", has_text="Inmuebles").click()
    page.wait_for_load_state("networkidle")

    assert "/inmuebles/" in page.url


def test_la_pagina_no_lanza_errores_de_javascript(page):
    errores = []
    page.on("pageerror", lambda e: errores.append(str(e)))
    page.reload(wait_until="networkidle")
    page.locator("nav button", has_text="Patrimonio").click()
    page.wait_for_timeout(300)

    assert errores == []
