"""Feed iCalendar.

Existe para el último tramo: Lares ya sabe qué vence, pero eso tiene que
aparecer donde la persona ya mira.

Lo que se prueba es lo que decide si el feed sirve o estorba: que un evento se
mueva en vez de duplicarse, que lo cumplido desaparezca, y que no se filtre nada
que no deba salir de casa.
"""

import datetime as dt

import pytest

from lares.core.models import Account, Document, Household, Obligation, Party
from lares.core.services import calendar as cal
from lares.core.services import obligations

HOY = dt.date.today()


@pytest.fixture
def con_vencimientos(scoped):
    Document.objects.create(
        household=scoped, title="Pasaporte", doc_type="passport",
        expires_on=HOY + dt.timedelta(days=200),
    )
    obligations.materialize(scoped, HOY)
    return scoped


def _eventos(texto: str) -> list[dict]:
    """Desdobla el plegado de líneas y parte por eventos."""
    plano = texto.replace("\r\n ", "").replace("\r\n", "\n")
    salida = []
    for bloque in plano.split("BEGIN:VEVENT")[1:]:
        cuerpo = bloque.split("END:VEVENT")[0]
        campos = {}
        for linea in cuerpo.strip().split("\n"):
            if ":" in linea:
                clave, valor = linea.split(":", 1)
                # Desescapar, como haría cualquier cliente de calendario.
                valor = (valor.replace("\\n", "\n").replace("\\,", ",")
                         .replace("\\;", ";").replace("\\\\", "\\"))
                campos.setdefault(clave.split(";")[0], valor)
        campos["_raw"] = cuerpo
        salida.append(campos)
    return salida


# --- Estructura -------------------------------------------------------------


@pytest.mark.django_db
def test_el_feed_es_un_calendario_valido(con_vencimientos):
    texto = cal.feed(con_vencimientos)

    assert texto.startswith("BEGIN:VCALENDAR\r\n")
    assert texto.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in texto
    assert texto.endswith("\r\n")          # RFC 5545 pide CRLF


@pytest.mark.django_db
def test_los_vencimientos_son_eventos_de_dia_completo(con_vencimientos):
    """Un vencimiento no ocurre a las 3 de la mañana."""
    evento = _eventos(cal.feed(con_vencimientos))[0]

    assert "DTSTART;VALUE=DATE" in evento["_raw"]
    assert len(evento["DTSTART"]) == 8     # AAAAMMDD, sin hora


@pytest.mark.django_db
def test_cada_evento_lleva_sus_propios_avisos(con_vencimientos):
    """Así el calendario recuerda aunque este servidor esté apagado."""
    evento = _eventos(cal.feed(con_vencimientos))[0]

    assert "BEGIN:VALARM" in evento["_raw"]
    assert "TRIGGER:-P90D" in evento["_raw"]


@pytest.mark.django_db
def test_las_lineas_largas_se_pliegan(scoped):
    Obligation.objects.create(
        household=scoped, dedupe_key="x", due_on=HOY,
        title="Un título deliberadamente larguísimo " * 4,
    )
    texto = cal.feed(scoped)

    for linea in texto.split("\r\n"):
        assert len(linea.encode("utf-8")) <= 75, linea[:60]


@pytest.mark.django_db
def test_las_comas_y_los_punto_y_coma_se_escapan(scoped):
    Obligation.objects.create(
        household=scoped, dedupe_key="x", due_on=HOY,
        title="Predial, agua; luz",
    )
    # Escapadas dentro del archivo, tal como manda el RFC...
    assert r"Predial\, agua\; luz" in cal.feed(scoped)
    # ...y correctas al leerlas, como haría cualquier cliente de calendario.
    assert _eventos(cal.feed(scoped))[0]["SUMMARY"] == "Predial, agua; luz"


# --- Lo que hace que el feed sea usable -------------------------------------


@pytest.mark.django_db
def test_cambiar_la_fecha_mueve_el_evento_no_lo_duplica(scoped):
    """Sin un UID estable, el calendario se llena de fantasmas."""
    o = Obligation.objects.create(household=scoped, dedupe_key="poliza:renovar",
                                  due_on=HOY + dt.timedelta(days=30), title="Renovar")
    uid_antes = _eventos(cal.feed(scoped))[0]["UID"]

    o.due_on = HOY + dt.timedelta(days=45)
    o.save()
    eventos = _eventos(cal.feed(scoped))

    assert len(eventos) == 1
    assert eventos[0]["UID"] == uid_antes


@pytest.mark.django_db
def test_la_version_del_evento_sube_al_cambiar(scoped):
    """Sin SEQUENCE mayor, muchos clientes ignoran la actualización."""
    o = Obligation.objects.create(household=scoped, dedupe_key="x", due_on=HOY,
                                  title="Algo")
    antes = int(_eventos(cal.feed(scoped))[0]["SEQUENCE"])

    Obligation.objects.filter(pk=o.pk).update(
        updated_at=o.updated_at + dt.timedelta(days=3)
    )
    assert int(_eventos(cal.feed(scoped))[0]["SEQUENCE"]) > antes


@pytest.mark.django_db
def test_lo_cumplido_desaparece_del_calendario(scoped):
    """Si no, el feed se vuelve un archivo histórico y deja de leerse."""
    o = Obligation.objects.create(household=scoped, dedupe_key="x", due_on=HOY,
                                  title="Pagar el agua")
    assert len(_eventos(cal.feed(scoped))) == 1

    o.status = Obligation.Status.DONE
    o.save()
    assert _eventos(cal.feed(scoped)) == []


@pytest.mark.django_db
def test_se_puede_suscribir_solo_un_area(con_vencimientos, me):
    from lares.modules.vehicles.models import Vehicle

    Vehicle.objects.create(household=con_vencimientos, name="Mazda", kind="vehicle",
                           plates="JGT1234", owner=me)
    obligations.materialize(con_vencimientos, HOY)

    solo_coches = _eventos(cal.feed(con_vencimientos, source_prefix="vehicles"))
    assert solo_coches
    assert all("Pasaporte" not in e["SUMMARY"] for e in solo_coches)


# --- Privacidad y acceso ----------------------------------------------------


@pytest.mark.django_db
def test_el_feed_no_saca_saldos_ni_limites(scoped, me):
    from lares.modules.finance.models import CreditCard

    cuenta = Account.objects.create(household=scoped, name="Tarjeta",
                                    type=Account.Type.LIABILITY)
    CreditCard.objects.create(household=scoped, name="Tarjeta", kind="credit_card",
                              account=cuenta, last_four="9876", due_day=5,
                              credit_limit=60000, owner=me)
    obligations.materialize(scoped, HOY)

    assert "60000" not in cal.feed(scoped)      # el límite no sale


@pytest.mark.django_db
def test_el_modo_discreto_no_publica_los_titulos(scoped, me):
    """El token viaja en una URL, que es un secreto débil.

    Un título como «Tarjeta ****9876» no debería acabar en un calendario
    compartido solo porque la dirección se filtró.
    """
    from lares.modules.finance.models import CreditCard

    cuenta = Account.objects.create(household=scoped, name="Tarjeta",
                                    type=Account.Type.LIABILITY)
    CreditCard.objects.create(household=scoped, name="Tarjeta", kind="credit_card",
                              account=cuenta, last_four="9876", due_day=5, owner=me)
    obligations.materialize(scoped, HOY)

    abierto = cal.feed(scoped)
    discreto = cal.feed(scoped, discreet=True)

    assert "9876" in abierto
    assert "9876" not in discreto
    # Pero sigue sirviendo: se sabe que hay algo y de qué área.
    assert "Dinero" in discreto
    assert "BEGIN:VALARM" in discreto


@pytest.mark.django_db
def test_el_token_abre_el_feed_sin_sesion(client, household):
    token = household.rotate_calendar_token()
    respuesta = client.get(f"/calendario/{token}.ics")

    assert respuesta.status_code == 200
    assert respuesta["Content-Type"].startswith("text/calendar")


@pytest.mark.django_db
def test_un_token_inventado_no_abre_nada(client, household):
    household.rotate_calendar_token()
    assert client.get("/calendario/loquesea.ics").status_code == 404


@pytest.mark.django_db
def test_rotar_el_token_invalida_el_anterior(client, household):
    viejo = household.rotate_calendar_token()
    household.rotate_calendar_token()

    assert client.get(f"/calendario/{viejo}.ics").status_code == 404


@pytest.mark.django_db
def test_el_token_de_un_hogar_no_abre_el_de_otro(client, scoped):
    Obligation.objects.create(household=scoped, dedupe_key="x", due_on=HOY,
                              title="Secreto de esta casa")
    ajeno = Household.objects.create(name="Casa ajena", slug="ajena")
    token = ajeno.rotate_calendar_token()

    contenido = client.get(f"/calendario/{token}.ics").content.decode()
    assert "Secreto de esta casa" not in contenido


@pytest.mark.django_db
def test_se_puede_bajar_una_obligacion_suelta(sesion_admin, scoped):
    o = Obligation.objects.create(household=scoped, dedupe_key="x", due_on=HOY,
                                  title="Verificación", counterparty=None)
    respuesta = sesion_admin.get(f"/o/{o.pk}.ics")

    assert respuesta.status_code == 200
    assert b"Verificaci" in respuesta.content
    assert "attachment" in respuesta["Content-Disposition"]


@pytest.mark.django_db
def test_la_pagina_de_calendario_crea_el_token_sola(sesion_admin, household):
    assert household.calendar_token == ""
    contenido = sesion_admin.get("/calendario/").content.decode()

    household.refresh_from_db()
    assert household.calendar_token
    assert household.calendar_token in contenido


@pytest.mark.django_db
def test_la_contraparte_aparece_pero_no_los_datos_sensibles(scoped):
    gnp = Party.objects.create(household=scoped, name="GNP",
                               kind=Party.Kind.ORGANIZATION)
    Obligation.objects.create(household=scoped, dedupe_key="x", due_on=HOY,
                              title="Renovar póliza", counterparty=gnp,
                              amount=18500, currency="MXN")
    evento = _eventos(cal.feed(scoped))[0]

    assert "GNP" in evento["DESCRIPTION"]
    assert "18,500" in evento["SUMMARY"]
