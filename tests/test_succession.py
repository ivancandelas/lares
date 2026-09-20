"""Sucesión y emergencia: el interruptor no puede equivocarse.

Aquí lo que importa no es que libere, sino **cuándo no libera**. Un falso
positivo manda los datos de alguien vivo al correo de un tercero, y eso no se
deshace con un rollback.

Las tres reglas que se prueban:

    silencio medido     cuenta desde el último día que entró quien administra
    se avisa antes      el plazo abre una ventana de gracia, no una entrega
    volver lo cierra    entrar rearma lo avisado y revoca lo liberado
"""

import datetime as dt
import json
import zipfile

import pytest
from django.core import mail
from django.utils import timezone

from lares.core.models import (
    ContactPoint,
    Document,
    EmergencyContact,
    Event,
    Household,
    Membership,
    Party,
    User,
)
from lares.core.scoping import use_household
from lares.core.services import succession

HOY = dt.date.today()


@pytest.fixture
def casa(db):
    return Household.objects.create(name="Casa", slug="casa")


def _titular(casa, visto_hace=0):
    user = User.objects.create_user(username="yo@x.mx", email="yo@x.mx",
                                    password="x", display_name="Iván")
    return Membership.objects.create(
        household=casa, user=user, role=Membership.Role.OWNER,
        accepted_at=timezone.now(),
        last_seen_on=HOY - dt.timedelta(days=visto_hace),
    )


def _contacto(casa, **kwargs):
    datos = {"name": "Ana", "email": "ana@x.mx", "relationship": "hermana",
             "quiet_days": 60, "grace_days": 7}
    datos.update(kwargs)
    return EmergencyContact.objects.create(household=casa, **datos)


def _sesion(client, membresia):
    client.force_login(membresia.user)
    return client


# --- La medida del silencio -------------------------------------------------


@pytest.mark.django_db
def test_el_silencio_se_mide_desde_el_ultimo_dia_que_entraste(casa):
    _titular(casa, visto_hace=40)

    assert succession.days_quiet(casa) == 40


@pytest.mark.django_db
def test_lo_que_hace_el_hijo_no_cuenta_como_que_tu_entraste(casa):
    """El mecanismo habla del titular, no de cualquiera que use la casa."""
    _titular(casa, visto_hace=90)
    hijo = User.objects.create_user(username="h@x.mx", email="h@x.mx",
                                    password="x")
    Membership.objects.create(household=casa, user=hijo,
                              role=Membership.Role.MEMBER,
                              accepted_at=timezone.now(), last_seen_on=HOY)

    assert succession.days_quiet(casa) == 90


@pytest.mark.django_db
def test_sin_medida_no_se_libera_nada(casa):
    """Falta de dato no es «se murió». Es el peor error posible aquí."""
    user = User.objects.create_user(username="n@x.mx", email="n@x.mx",
                                    password="x")
    Membership.objects.create(household=casa, user=user,
                              role=Membership.Role.OWNER,
                              accepted_at=timezone.now())
    with use_household(casa):
        contacto = _contacto(casa)

    assert succession.days_quiet(casa) is None
    assert succession.review(casa)["avisados"] == 0
    contacto.refresh_from_db()
    assert contacto.state == EmergencyContact.State.ARMED


@pytest.mark.django_db
def test_navegar_deja_constancia_del_dia(casa, client, settings):
    """`last_login` no sirve: quien no cierra sesión lleva meses sin tocarlo."""
    settings.TENANCY_MODE = "multi"
    yo = _titular(casa, visto_hace=90)
    _sesion(client, yo).get("/")

    yo.refresh_from_db()
    assert yo.last_seen_on == HOY


# --- Avisar antes de entregar -----------------------------------------------


@pytest.mark.django_db
def test_el_plazo_avisa_pero_todavia_no_entrega(casa):
    _titular(casa, visto_hace=61)
    with use_household(casa):
        contacto = _contacto(casa)

        salida = succession.review(casa)

    contacto.refresh_from_db()
    assert salida["avisados"] == 1
    assert contacto.state == EmergencyContact.State.WARNED
    assert contacto.releases_on == HOY + dt.timedelta(days=7)
    assert not contacto.token


@pytest.mark.django_db
def test_el_aviso_va_al_titular_no_al_contacto(casa):
    """Nadie quiere esa llamada mientras el hermano está de viaje."""
    _titular(casa, visto_hace=61)
    with use_household(casa):
        _contacto(casa)
        succession.review(casa)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["yo@x.mx"]


@pytest.mark.django_db
def test_antes_del_plazo_no_pasa_nada(casa):
    _titular(casa, visto_hace=59)
    with use_household(casa):
        contacto = _contacto(casa)
        succession.review(casa)

    contacto.refresh_from_db()
    assert contacto.state == EmergencyContact.State.ARMED
    assert not mail.outbox


@pytest.mark.django_db
def test_revisar_dos_veces_el_mismo_dia_no_avisa_dos_veces(casa):
    _titular(casa, visto_hace=61)
    with use_household(casa):
        _contacto(casa)
        succession.review(casa)
        segunda = succession.review(casa)

    assert segunda["avisados"] == 0
    assert len(mail.outbox) == 1


# --- La entrega -------------------------------------------------------------


@pytest.mark.django_db
def test_pasada_la_gracia_se_libera_y_le_llega_el_enlace(casa):
    _titular(casa, visto_hace=61)
    with use_household(casa):
        contacto = _contacto(casa)
        succession.review(casa)
        contacto.refresh_from_db()
        # Siete días después, y el titular sigue sin aparecer.
        contacto.warned_on = HOY - dt.timedelta(days=7)
        contacto.save(update_fields=["warned_on"])
        salida = succession.review(casa)

    contacto.refresh_from_db()
    assert salida["liberados"] == 1
    assert contacto.state == EmergencyContact.State.RELEASED
    assert contacto.token
    assert mail.outbox[-1].to == ["ana@x.mx"]
    assert contacto.token in mail.outbox[-1].body


@pytest.mark.django_db
def test_si_no_hay_correo_propio_se_usa_el_de_la_ficha(casa):
    """Y se encuentra desde una tarea de fondo, sin hogar activo en el hilo."""
    with use_household(casa):
        ana = Party.objects.create(household=casa, name="Ana")
        ContactPoint.objects.create(household=casa, party=ana,
                                    channel=ContactPoint.Channel.EMAIL,
                                    value="ana@ficha.mx")
        contacto = _contacto(casa, party=ana, email="")

    assert contacto.where == "ana@ficha.mx"


@pytest.mark.django_db
def test_el_correo_escrito_a_mano_manda_sobre_el_de_la_ficha(casa):
    with use_household(casa):
        ana = Party.objects.create(household=casa, name="Ana")
        ContactPoint.objects.create(household=casa, party=ana,
                                    channel=ContactPoint.Channel.EMAIL,
                                    value="ana@ficha.mx")
        contacto = _contacto(casa, party=ana, email="ana@otro.mx")

    assert contacto.where == "ana@otro.mx"


# --- Volver lo cierra -------------------------------------------------------


@pytest.mark.django_db
def test_volver_a_entrar_cancela_el_aviso(casa):
    titular = _titular(casa, visto_hace=61)
    with use_household(casa):
        contacto = _contacto(casa)
        succession.review(casa)

        titular.last_seen_on = HOY
        titular.save(update_fields=["last_seen_on"])
        salida = succession.review(casa)

    contacto.refresh_from_db()
    assert salida["rearmados"] == 1
    assert contacto.state == EmergencyContact.State.ARMED
    assert contacto.warned_on is None


@pytest.mark.django_db
def test_volver_a_entrar_revoca_el_paquete_ya_liberado(casa, client):
    """Quien vuelve está vivo, y el enlace deja de funcionar en el acto."""
    titular = _titular(casa, visto_hace=61)
    with use_household(casa):
        contacto = _contacto(casa)
        succession.release(contacto)
        token = contacto.token

    assert client.get(f"/sucesion/{token}/").status_code == 200

    titular.last_seen_on = HOY
    titular.save(update_fields=["last_seen_on"])
    succession.review(casa)

    assert client.get(f"/sucesion/{token}/").status_code == 404


@pytest.mark.django_db
def test_sigo_aqui_cierra_todo_a_mano(casa):
    _titular(casa, visto_hace=61)
    with use_household(casa):
        contacto = _contacto(casa)
        succession.release(contacto)

        assert succession.im_here(casa) == 1

    contacto.refresh_from_db()
    assert contacto.state == EmergencyContact.State.ARMED
    assert not contacto.token


@pytest.mark.django_db
def test_lo_que_pasa_queda_en_la_linea_de_tiempo(casa):
    _titular(casa, visto_hace=61)
    with use_household(casa):
        contacto = _contacto(casa)
        succession.release(contacto)
        succession.rearm(contacto)

    verbos = list(Event.objects.filter(household=casa)
                  .values_list("verb", flat=True))
    assert "succession.released" in verbos
    assert "succession.rearmed" in verbos


@pytest.mark.django_db
def test_un_contacto_desactivado_no_entra_en_la_revision(casa):
    _titular(casa, visto_hace=400)
    with use_household(casa):
        contacto = _contacto(casa, state=EmergencyContact.State.OFF)
        succession.review(casa)

    contacto.refresh_from_db()
    assert contacto.state == EmergencyContact.State.OFF


# --- El paquete -------------------------------------------------------------


@pytest.mark.django_db
def test_el_paquete_lleva_solo_las_secciones_elegidas(casa):
    with use_household(casa):
        Party.objects.create(household=casa, name="Ana")
        contacto = _contacto(casa, sections=["personas"])
        paquete = succession.package(casa, contacto)

    assert "personas" in paquete
    assert "patrimonio" not in paquete
    assert "deudas" not in paquete


@pytest.mark.django_db
def test_sin_secciones_elegidas_va_el_paquete_completo(casa):
    with use_household(casa):
        contacto = _contacto(casa, sections=[])
        paquete = succession.package(casa, contacto)

    assert set(paquete["secciones"]) == set(succession.TODAS)


@pytest.mark.django_db
def test_una_organizacion_sin_telefono_no_entra_en_a_quien_llamar(casa):
    """«A quién llamar» sin número no sirve de nada; una persona sí se nombra."""
    with use_household(casa):
        Party.objects.create(household=casa, name="Banco sin teléfono",
                             kind=Party.Kind.ORGANIZATION)
        Party.objects.create(household=casa, name="Luis")
        contacto = _contacto(casa)
        paquete = succession.package(casa, contacto)

    nombres = [p["party"].name for p in paquete["personas"]]
    assert "Luis" in nombres
    assert "Banco sin teléfono" not in nombres


@pytest.mark.django_db
def test_los_pasos_salen_de_lo_que_hay_y_no_de_una_plantilla(casa):
    with use_household(casa):
        Party.objects.create(household=casa, name="Ana")
        Document.objects.create(household=casa, title="Escritura",
                                expires_on=HOY + dt.timedelta(days=400))
        contacto = _contacto(casa)
        paquete = succession.package(casa, contacto)

    titulos = [p["titulo"] for p in paquete["pasos"]]
    assert "Avisa a quien toca" in titulos
    assert "Reúne los papeles" in titulos


@pytest.mark.django_db
def test_un_documento_privado_se_nombra_pero_no_se_entrega(casa):
    with use_household(casa):
        Document.objects.create(
            household=casa, title="Testamento",
            confidentiality=Document.Confidentiality.SECRET)
        contacto = _contacto(casa)
        paquete = succession.package(casa, contacto)

    entrada = paquete["documentos"][0]
    assert entrada["doc"].title == "Testamento"
    assert not entrada["abierto"]


@pytest.mark.django_db
def test_el_enlace_del_paquete_se_abre_sin_sesion(casa, client):
    with use_household(casa):
        Party.objects.create(household=casa, name="Aseguradora GNP",
                             kind=Party.Kind.ORGANIZATION)
        contacto = _contacto(casa)
        succession.release(contacto)

    respuesta = client.get(f"/sucesion/{contacto.token}/")

    assert respuesta.status_code == 200
    assert "Ana" in respuesta.content.decode()


@pytest.mark.django_db
def test_cada_apertura_se_cuenta(casa, client):
    with use_household(casa):
        contacto = _contacto(casa)
        succession.release(contacto)

    client.get(f"/sucesion/{contacto.token}/")
    client.get(f"/sucesion/{contacto.token}/")

    contacto.refresh_from_db()
    assert contacto.hits == 2
    assert contacto.last_seen_at


@pytest.mark.django_db
def test_un_token_inventado_no_abre_nada(casa, client):
    assert client.get("/sucesion/loquesea/").status_code == 404


@pytest.mark.django_db
def test_el_zip_se_puede_leer_sin_lares(casa, client):
    """Si para leer el paquete hace falta un Django, no sirve el día que sirve."""
    with use_household(casa):
        Party.objects.create(household=casa, name="Ana")
        contacto = _contacto(casa)
        succession.release(contacto)

    respuesta = client.get(f"/sucesion/{contacto.token}/paquete.zip")
    assert respuesta.status_code == 200

    import io

    with zipfile.ZipFile(io.BytesIO(b"".join(respuesta.streaming_content))) as zf:
        assert "paquete.json" in zf.namelist()
        assert "LEEME.txt" in zf.namelist()
        datos = json.loads(zf.read("paquete.json"))

    assert datos["formato"] == "lares-sucesion/1"
    assert datos["hogar"] == "Casa"
    assert any(p["nombre"] == "Ana" for p in datos["personas"])


@pytest.mark.django_db
def test_un_documento_normal_si_se_abre_y_viaja_en_el_zip(casa, client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    with use_household(casa):
        doc = Document.objects.create(
            household=casa, title="Escritura",
            file=SimpleUploadedFile("escritura.pdf", b"%PDF-1.4 el papel"))
        contacto = _contacto(casa)
        succession.release(contacto)

    respuesta = client.get(f"/sucesion/{contacto.token}/d/{doc.pk}/")
    assert respuesta.status_code == 200
    assert b"el papel" in b"".join(respuesta.streaming_content)

    import io

    zip_http = client.get(f"/sucesion/{contacto.token}/paquete.zip")
    with zipfile.ZipFile(io.BytesIO(b"".join(zip_http.streaming_content))) as zf:
        assert "documentos/escritura.pdf" in zf.namelist()


@pytest.mark.django_db
def test_un_documento_confidencial_no_se_baja_por_el_enlace(casa, client):
    with use_household(casa):
        doc = Document.objects.create(
            household=casa, title="Testamento",
            confidentiality=Document.Confidentiality.PRIVATE)
        contacto = _contacto(casa)
        succession.release(contacto)

    respuesta = client.get(f"/sucesion/{contacto.token}/d/{doc.pk}/")

    assert respuesta.status_code == 404


@pytest.mark.django_db
def test_los_documentos_no_se_bajan_si_esa_seccion_no_va(casa, client):
    with use_household(casa):
        doc = Document.objects.create(household=casa, title="Escritura")
        contacto = _contacto(casa, sections=["personas"])
        succession.release(contacto)

    assert client.get(
        f"/sucesion/{contacto.token}/d/{doc.pk}/").status_code == 404


# --- Las pantallas del titular ----------------------------------------------


@pytest.mark.django_db
def test_la_pantalla_se_ve_y_la_vista_previa_tambien(casa, client, settings):
    settings.TENANCY_MODE = "multi"
    yo = _titular(casa)
    with use_household(casa):
        contacto = _contacto(casa)

    sesion = _sesion(client, yo)
    assert sesion.get("/sucesion/").status_code == 200
    previa = sesion.get(f"/sucesion/{contacto.pk}/vista/")
    assert previa.status_code == 200
    assert "Ana" in previa.content.decode()


@pytest.mark.django_db
def test_quien_no_administra_no_toca_la_sucesion(casa, client, settings):
    """Decide a quién se le abre el hogar entero: no es de cualquiera."""
    settings.TENANCY_MODE = "multi"
    user = User.objects.create_user(username="h@x.mx", email="h@x.mx",
                                    password="x")
    hijo = Membership.objects.create(household=casa, user=user,
                                     role=Membership.Role.ADULT,
                                     accepted_at=timezone.now())

    assert _sesion(client, hijo).get("/sucesion/").status_code == 403


@pytest.mark.django_db
def test_el_formulario_exige_un_correo_al_que_avisar(casa, settings):
    """Sin correo no hay a dónde mandarlo, y eso se descubre el peor día."""
    from lares.core.forms import EmergencyContactForm

    with use_household(casa):
        form = EmergencyContactForm(
            {"name": "Ana", "quiet_days": 60, "grace_days": 7},
            household=casa)

        assert not form.is_valid()
        assert "email" in form.errors
