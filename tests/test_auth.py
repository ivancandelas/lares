"""Nada es publico: la instalacion puede estar expuesta."""

import pytest


@pytest.mark.django_db
def test_el_tablero_exige_sesion(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith("/entrar/")


@pytest.mark.django_db
def test_la_pantalla_de_entrada_es_publica(client):
    assert client.get("/entrar/").status_code == 200


@pytest.mark.django_db
def test_cambiar_la_contrasena_exige_sesion(client):
    respuesta = client.get("/cuenta/contrasena/")
    assert respuesta.status_code == 302
    assert respuesta["Location"].startswith("/entrar/")


@pytest.mark.django_db
def test_la_pantalla_pinta_los_tres_campos(sesion_admin):
    """`core/form.html` recorre `form.groups`.

    Un formulario sin eso se renderiza vacío y sin error: la página responde
    200 y no hay ni un campo. Por eso se comprueban los campos y no el código.
    """
    html = sesion_admin.get("/cuenta/contrasena/").content.decode()

    for campo in ("old_password", "new_password1", "new_password2"):
        assert f'name="{campo}"' in html


@pytest.mark.django_db
def test_se_cambia_y_la_sesion_sobrevive(sesion_admin, django_user_model):
    respuesta = sesion_admin.post("/cuenta/contrasena/", {
        "old_password": "x",
        "new_password1": "traigo-lena-al-fuego",
        "new_password2": "traigo-lena-al-fuego",
    })
    assert respuesta.status_code == 302

    user = django_user_model.objects.get(email="ivan@example.com")
    assert user.check_password("traigo-lena-al-fuego")

    # Y no te echa: sin `update_session_auth_hash` el hash de la sesión deja de
    # cuadrar y la petición siguiente cae en la pantalla de entrada. Parecería
    # que falló justo cuando funcionó.
    assert sesion_admin.get("/").status_code == 200


@pytest.mark.django_db
def test_no_se_cambia_sin_la_actual(sesion_admin, django_user_model):
    """Una sesión abierta en un equipo ajeno no puede quedarse con la cuenta."""
    respuesta = sesion_admin.post("/cuenta/contrasena/", {
        "old_password": "la-que-no-es",
        "new_password1": "traigo-lena-al-fuego",
        "new_password2": "traigo-lena-al-fuego",
    })

    assert respuesta.status_code == 200
    assert django_user_model.objects.get(email="ivan@example.com").check_password("x")


@pytest.mark.django_db
def test_un_miembro_restringido_tambien_puede(client, django_user_model, household):
    """Sin ámbito propio: `sees("core")` concede siempre.

    Si esta pantalla cayera en el ámbito `admin` -como «El hogar»-, a quien se
    le restringió el dinero no podría cambiar su clave, y eso acaba en
    contraseñas compartidas por mensaje.
    """
    from lares.core.models import Membership

    user = django_user_model.objects.create_user(
        username="hija", email="hija@example.com", password="x"
    )
    Membership.objects.create(
        household=household, user=user, role=Membership.Role.MEMBER,
        scopes=["vehicles"], accepted_at="2026-01-01T00:00:00Z",
    )
    client.force_login(user)

    assert client.get("/cuenta/contrasena/").status_code == 200
