"""Auditoría de accesos (PRIV-06).

La documentación promete que el acceso del contador «queda en la línea de
tiempo». Estas pruebas son las que hacen que eso sea verdad y siga siéndolo.

Lo que más importa aquí es **lo que no se apunta**: un formulario que vuelve
con errores no cambió nada, y una bitácora llena de intentos fallidos o de un
GET por página no la lee nadie, que es la única forma de que una auditoría
no sirva.
"""

import datetime as dt

import pytest
from django.utils import timezone

from lares.core.models import Event, Household, Membership, Party, Share, User
from lares.core.scoping import use_household
from lares.core.services import audit


@pytest.fixture
def multi(settings):
    settings.TENANCY_MODE = "multi"
    return settings


@pytest.fixture
def casa(db):
    return Household.objects.create(name="Casa", slug="casa")


def _miembro(casa, correo, rol=Membership.Role.MEMBER, scopes=None):
    user = User.objects.create_user(username=correo, email=correo,
                                    password="x", display_name=correo)
    return Membership.objects.create(
        household=casa, user=user, role=rol, scopes=scopes or [],
        accepted_at=timezone.now(),
    )


def _sesion(client, membresia):
    client.force_login(membresia.user)
    return client


def _eventos(casa, verbo=None):
    consulta = Event.objects.filter(household=casa)
    return list(consulta.filter(verb=verbo) if verbo else consulta)


# --- Lo que cambia queda apuntado -------------------------------------------


@pytest.mark.django_db
def test_lo_que_cambia_algo_queda_en_la_bitacora(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    _sesion(client, yo).post("/personas/nueva/", {"kind": "person",
                                                  "name": "Mariana"})

    [evento] = _eventos(casa, audit.WRITE)
    assert evento.actor == yo.user
    assert evento.summary == "/personas/nueva/"


@pytest.mark.django_db
def test_un_formulario_con_errores_no_cambio_nada_y_no_se_apunta(multi, casa,
                                                                 client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    respuesta = _sesion(client, yo).post("/personas/nueva/", {})

    assert respuesta.status_code == 200      # el formulario, con sus errores
    assert _eventos(casa, audit.WRITE) == []


@pytest.mark.django_db
def test_una_pantalla_nueva_queda_auditada_sin_tocarla(multi, casa, client):
    """Va en el middleware justo por esto: no hay nada de lo que acordarse."""
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    _sesion(client, yo).post("/hogar/datos/", {
        "name": "Otra casa", "country": "MX", "subdivision": "MX-JAL",
        "timezone": "America/Mexico_City", "currency": "MXN"})

    assert [e.summary for e in _eventos(casa, audit.WRITE)] == ["/hogar/datos/"]


# --- De las lecturas, solo las que importan ---------------------------------


@pytest.mark.django_db
def test_se_apunta_lo_que_mira_quien_no_es_de_casa(multi, casa, client):
    contador = _miembro(casa, "contador@x.mx", Membership.Role.PROFESSIONAL,
                        scopes=["taxes"])
    contador.expires_on = dt.date.today() + dt.timedelta(days=30)
    contador.save(update_fields=["expires_on"])

    _sesion(client, contador).get("/impuestos/")

    [evento] = _eventos(casa, audit.READ)
    assert evento.actor == contador.user
    assert evento.summary == "/impuestos/"
    assert evento.payload["role"] == "professional"


@pytest.mark.django_db
def test_lo_que_mira_la_familia_no_se_apunta(multi, casa, client):
    """Un GET por página de cada miembro es un log de servidor, no una auditoría."""
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    sesion = _sesion(client, yo)
    sesion.get("/")
    sesion.get("/patrimonio/")

    assert _eventos(casa, audit.READ) == []


@pytest.mark.django_db
def test_la_misma_pantalla_el_mismo_dia_se_apunta_una_vez(multi, casa, client):
    invitado = _miembro(casa, "mira@x.mx", Membership.Role.VIEWER)

    sesion = _sesion(client, invitado)
    sesion.get("/patrimonio/")
    sesion.get("/patrimonio/")
    sesion.get("/patrimonio/")

    assert len(_eventos(casa, audit.READ)) == 1


@pytest.mark.django_db
def test_dos_pantallas_distintas_son_dos_lineas(multi, casa, client):
    invitado = _miembro(casa, "mira@x.mx", Membership.Role.VIEWER)

    sesion = _sesion(client, invitado)
    sesion.get("/patrimonio/")
    sesion.get("/personas/")

    assert len(_eventos(casa, audit.READ)) == 2


# --- Lo que se abre desde fuera ---------------------------------------------


@pytest.mark.django_db
def test_abrir_un_enlace_compartido_queda_apuntado(casa, client):
    with use_household(casa):
        Party.objects.create(household=casa, name="Mariana")
        share = Share.objects.create(household=casa, label="Los de la boda",
                                     target="familia")

    client.get(f"/c/{share.token}/")

    [evento] = _eventos(casa, audit.OPEN)
    assert evento.actor is None          # no hay sesión: es de fuera
    assert "Los de la boda" in evento.summary


@pytest.mark.django_db
def test_recargar_el_enlace_no_llena_la_bitacora(casa, client):
    with use_household(casa):
        share = Share.objects.create(household=casa, label="Los de la boda",
                                     target="familia")

    for _ in range(4):
        client.get(f"/c/{share.token}/")

    assert len(_eventos(casa, audit.OPEN)) == 1


@pytest.mark.django_db
def test_abrir_un_paquete_de_sucesion_queda_apuntado(casa, client):
    from lares.core.models import EmergencyContact
    from lares.core.services import succession

    with use_household(casa):
        contacto = EmergencyContact.objects.create(
            household=casa, name="Ana", email="ana@x.mx")
        succession.release(contacto)

    client.get(f"/sucesion/{contacto.token}/")

    [evento] = _eventos(casa, audit.OPEN)
    assert "Ana" in evento.summary


# --- La pantalla ------------------------------------------------------------


@pytest.mark.django_db
def test_la_bitacora_se_ve_y_se_filtra(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)
    sesion = _sesion(client, yo)
    sesion.post("/personas/nueva/", {"kind": "person", "name": "Mariana"})

    contenido = sesion.get("/hogar/bitacora/").content.decode()
    assert "Cambió algo" in contenido
    assert "/personas/nueva/" in contenido

    # Un alta es «qué ha cambiado», no «quién ha mirado».
    cambios = sesion.get("/hogar/bitacora/?tipo=cambios").content.decode()
    assert "/personas/nueva/" in cambios

    miradas = sesion.get("/hogar/bitacora/?tipo=accesos").content.decode()
    assert "/personas/nueva/" not in miradas


@pytest.mark.django_db
def test_la_bitacora_es_de_quien_administra(multi, casa, client):
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.ADULT)

    assert _sesion(client, hijo).get("/hogar/bitacora/").status_code == 403


@pytest.mark.django_db
def test_entrar_tiene_su_propia_linea(multi, casa, client):
    """Es la que se busca al revisar una bitácora, y no es «cambió algo»."""
    _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    client.post("/entrar/", {"username": "yo@x.mx", "password": "x"})

    [evento] = _eventos(casa, audit.LOGIN)
    assert audit.label_of(evento) == "Entró"
    assert _eventos(casa, audit.WRITE) == []


@pytest.mark.django_db
def test_salir_no_deja_linea(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    _sesion(client, yo).post("/salir/")

    assert _eventos(casa) == []
