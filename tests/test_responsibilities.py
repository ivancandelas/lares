"""Quién se encarga de qué (PER-03).

En un hogar de dos adultos, la mitad de las discusiones no son sobre si algo se
hizo, sino sobre **de quién era**. Lo que se prueba aquí:

    se pregunta, no se copia    la obligación no guarda una copia del responsable
    lo puntual manda            `assigned_to` gana a quien se encarga de la cosa
    volver a repartir no borra  la arista anterior se cierra, no desaparece
    el aviso llega a quien toca y si no se le puede escribir, va a todos
"""

import datetime as dt

import pytest
from django.core import mail
from django.utils import timezone

from lares.core.models import (
    ContactPoint,
    Household,
    Link,
    Membership,
    Obligation,
    Party,
    User,
)
from lares.core.scoping import use_household
from lares.core.services import responsibilities

HOY = dt.date.today()


@pytest.fixture
def casa(db):
    return Household.objects.create(name="Casa", slug="casa")


@pytest.fixture
def coche(casa):
    """Un recurso de verdad, del módulo de vehículos."""
    from lares.modules.vehicles.models import Vehicle

    with use_household(casa):
        yield Vehicle.objects.create(household=casa, name="Mazda CX-5",
                                     kind="vehicle", plates="ABC-123")


def _persona(casa, nombre, correo=None):
    with use_household(casa):
        party = Party.objects.create(household=casa, name=nombre)
        if correo:
            ContactPoint.objects.create(household=casa, party=party,
                                        channel=ContactPoint.Channel.EMAIL,
                                        value=correo)
    return party


def _obligacion(casa, sujeto, titulo="Verificación", dias=3, **kwargs):
    from django.contrib.contenttypes.models import ContentType

    with use_household(casa):
        return Obligation.objects.create(
            household=casa, dedupe_key=f"{titulo}-{dias}", title=titulo,
            due_on=HOY + dt.timedelta(days=dias),
            subject_type=ContentType.objects.get_for_model(sujeto.__class__),
            subject_id=sujeto.pk, **kwargs,
        )


# --- Se pregunta, no se copia -----------------------------------------------


@pytest.mark.django_db
def test_la_obligacion_hereda_de_la_cosa_sin_guardar_nada(casa, coche):
    mariana = _persona(casa, "Mariana")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        obligacion = _obligacion(casa, coche)

        mapa = responsibilities.responsible_map(casa)
        [anotada] = responsibilities.annotate([obligacion], mapa)

    assert anotada.responsible == mariana
    # Y no se copió: la columna sigue vacía.
    obligacion.refresh_from_db()
    assert obligacion.assigned_to is None


@pytest.mark.django_db
def test_cambiar_de_encargado_cambia_lo_que_ya_estaba(casa, coche):
    """Es lo que una copia al materializar habría dejado desactualizado."""
    mariana = _persona(casa, "Mariana")
    luis = _persona(casa, "Luis")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        obligacion = _obligacion(casa, coche)
        responsibilities.set_responsible(casa, coche, luis)

        mapa = responsibilities.responsible_map(casa)
        [anotada] = responsibilities.annotate([obligacion], mapa)

    assert anotada.responsible == luis


@pytest.mark.django_db
def test_esta_vez_le_toca_a_otro(casa, coche):
    """Lo puntual manda sobre lo permanente."""
    mariana = _persona(casa, "Mariana")
    luis = _persona(casa, "Luis")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        obligacion = _obligacion(casa, coche, assigned_to=luis)

        mapa = responsibilities.responsible_map(casa)
        [anotada] = responsibilities.annotate([obligacion], mapa)

    assert anotada.responsible == luis


@pytest.mark.django_db
def test_sin_nadie_a_cargo_la_obligacion_no_es_de_nadie(casa, coche):
    with use_household(casa):
        obligacion = _obligacion(casa, coche)
        mapa = responsibilities.responsible_map(casa)
        [anotada] = responsibilities.annotate([obligacion], mapa)

    assert anotada.responsible is None


# --- Repartir no borra el reparto anterior ----------------------------------


@pytest.mark.django_db
def test_al_cambiar_de_encargado_la_arista_anterior_se_cierra(casa, coche):
    mariana = _persona(casa, "Mariana")
    luis = _persona(casa, "Luis")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        responsibilities.set_responsible(casa, coche, luis)

        vivas = Link.objects.filter(role=responsibilities.CARED_BY,
                                    valid_to__isnull=True)
        cerradas = Link.objects.filter(role=responsibilities.CARED_BY,
                                       valid_to__isnull=False)

        assert vivas.count() == 1
        assert cerradas.count() == 1
        assert responsibilities.responsible_of(coche) == luis


@pytest.mark.django_db
def test_repetir_el_mismo_encargado_no_duplica_aristas(casa, coche):
    mariana = _persona(casa, "Mariana")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        responsibilities.set_responsible(casa, coche, mariana)

        assert Link.objects.filter(role=responsibilities.CARED_BY).count() == 1


@pytest.mark.django_db
def test_se_puede_dejar_algo_sin_nadie(casa, coche):
    mariana = _persona(casa, "Mariana")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        responsibilities.set_responsible(casa, coche, None)

        assert responsibilities.responsible_of(coche) is None
        # Pero queda el historial de que fue suyo.
        assert Link.objects.filter(role=responsibilities.CARED_BY).count() == 1


# --- El reparto -------------------------------------------------------------


@pytest.mark.django_db
def test_el_reparto_separa_lo_de_cada_quien_y_lo_que_no_es_de_nadie(casa, coche):
    from lares.modules.vehicles.models import Vehicle

    mariana = _persona(casa, "Mariana")
    with use_household(casa):
        otro = Vehicle.objects.create(household=casa, name="Vento",
                                      kind="vehicle", plates="XYZ-987")
        responsibilities.set_responsible(casa, coche, mariana)
        _obligacion(casa, coche, "Verificación")
        _obligacion(casa, otro, "Refrendo", dias=10)

        datos = responsibilities.split(casa)

    [suyo] = datos["reparto"]
    assert suyo["party"] == mariana
    assert [o.title for o in suyo["obligaciones"]] == ["Verificación"]
    assert [o.title for o in datos["huerfanas"]] == ["Refrendo"]
    assert [r.name for r in datos["sin_dueno"]] == ["Vento"]


@pytest.mark.django_db
def test_el_reparto_cuenta_lo_vencido_aparte(casa, coche):
    mariana = _persona(casa, "Mariana")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        _obligacion(casa, coche, "Tarde", dias=-5,
                    status=Obligation.Status.OVERDUE)
        _obligacion(casa, coche, "A tiempo", dias=20)

        [suyo] = responsibilities.split(casa)["reparto"]

    assert len(suyo["obligaciones"]) == 2
    assert [o.title for o in suyo["vencidas"]] == ["Tarde"]


# --- El aviso llega a quien le toca -----------------------------------------


@pytest.mark.django_db
def test_el_recordatorio_va_a_quien_se_encarga(casa, coche):
    from lares.core.models import Reminder
    from lares.core.services import notify

    user = User.objects.create_user(username="todos@x.mx", email="todos@x.mx",
                                    password="x")
    Membership.objects.create(household=casa, user=user,
                              role=Membership.Role.OWNER,
                              accepted_at=timezone.now())
    mariana = _persona(casa, "Mariana", correo="mariana@x.mx")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        obligacion = _obligacion(casa, coche)
        Reminder.objects.create(household=casa, obligation=obligacion,
                                fire_on=HOY)

    notify.send_due_reminders(casa)

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["mariana@x.mx"]
    assert "Mariana" in mail.outbox[0].body


@pytest.mark.django_db
def test_si_no_se_le_puede_escribir_el_aviso_va_a_todos(casa, coche):
    """Un aviso que no sale es peor que uno de más: nadie se entera de que falta."""
    from lares.core.models import Reminder
    from lares.core.services import notify

    user = User.objects.create_user(username="todos@x.mx", email="todos@x.mx",
                                    password="x")
    Membership.objects.create(household=casa, user=user,
                              role=Membership.Role.OWNER,
                              accepted_at=timezone.now())
    sin_correo = _persona(casa, "Abuelo")
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, sin_correo)
        obligacion = _obligacion(casa, coche)
        Reminder.objects.create(household=casa, obligation=obligacion,
                                fire_on=HOY)

    notify.send_due_reminders(casa)

    assert mail.outbox[0].to == ["todos@x.mx"]


# --- Las pantallas ----------------------------------------------------------


@pytest.mark.django_db
def test_se_dice_de_quien_es_desde_la_ficha(casa, coche, client,
                                            django_user_model):
    mariana = _persona(casa, "Mariana")
    user = django_user_model.objects.create_user(
        username="yo@x.mx", email="yo@x.mx", password="x")
    client.force_login(user)

    respuesta = client.post(f"/r/{coche.pk}/encargado/", {"party": mariana.pk})

    assert respuesta.status_code == 302
    with use_household(casa):
        assert responsibilities.responsible_of(coche) == mariana

    ficha = client.get(f"/r/{coche.pk}/").content.decode()
    assert "Se encarga" in ficha and "Mariana" in ficha


@pytest.mark.django_db
def test_la_pantalla_del_reparto_se_ve(casa, coche, client, django_user_model):
    mariana = _persona(casa, "Mariana")
    user = django_user_model.objects.create_user(
        username="yo@x.mx", email="yo@x.mx", password="x")
    client.force_login(user)
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        _obligacion(casa, coche)

    contenido = client.get("/reparto/").content.decode()

    assert "Mariana" in contenido
    assert "Mazda CX-5" in contenido
    assert "Verificación" in contenido


# --- Pasarle una obligación a alguien, desde donde se está mirando ----------


@pytest.mark.django_db
def test_se_le_puede_pasar_una_obligacion_a_otro(casa, coche, client,
                                                 django_user_model):
    """Era la mitad de PER-03 que no tenía puerta: se leía y no se podía poner."""
    luis = _persona(casa, "Luis")
    user = django_user_model.objects.create_user(
        username="yo@x.mx", email="yo@x.mx", password="x")
    client.force_login(user)
    with use_household(casa):
        obligacion = _obligacion(casa, coche)

    respuesta = client.post(f"/o/{obligacion.pk}/encargado/",
                            {"party": luis.pk, "volver": "/reparto/"})

    obligacion.refresh_from_db()
    assert respuesta.status_code == 302
    assert respuesta["Location"] == "/reparto/"
    assert obligacion.assigned_to == luis


@pytest.mark.django_db
def test_se_le_puede_devolver_a_quien_lleve_la_cosa(casa, coche, client,
                                                    django_user_model):
    mariana = _persona(casa, "Mariana")
    luis = _persona(casa, "Luis")
    user = django_user_model.objects.create_user(
        username="yo@x.mx", email="yo@x.mx", password="x")
    client.force_login(user)
    with use_household(casa):
        responsibilities.set_responsible(casa, coche, mariana)
        obligacion = _obligacion(casa, coche, assigned_to=luis)

    client.post(f"/o/{obligacion.pk}/encargado/", {"party": ""})

    obligacion.refresh_from_db()
    assert obligacion.assigned_to is None
    with use_household(casa):
        mapa = responsibilities.responsible_map(casa)
        [anotada] = responsibilities.annotate([obligacion], mapa)
    assert anotada.responsible == mariana


@pytest.mark.django_db
def test_no_se_vuelve_a_donde_diga_un_tercero(casa, coche, client,
                                              django_user_model):
    """«//otrositio.com» es una dirección absoluta disfrazada de ruta."""
    user = django_user_model.objects.create_user(
        username="yo@x.mx", email="yo@x.mx", password="x")
    client.force_login(user)
    with use_household(casa):
        obligacion = _obligacion(casa, coche)

    respuesta = client.post(f"/o/{obligacion.pk}/encargado/",
                            {"party": "", "volver": "//evil.example/"})

    assert respuesta["Location"] == "/reparto/"
