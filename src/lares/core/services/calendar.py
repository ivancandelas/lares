"""Feed iCalendar de los vencimientos.

Es el ultimo tramo del producto: Lares ya sabe que vence y cuando, pero eso
tiene que aparecer donde la persona ya mira. Un feed suscribible funciona en
Google, Apple, Outlook y Thunderbird sin pedirle la contrasena a nadie.

Cuatro detalles deciden si sirve o estorba:

  1. UID estable por obligacion, derivado del dedupe_key: cambiar la fecha
     MUEVE el evento en vez de duplicarlo. Sin esto el calendario se llena de
     fantasmas y la persona se desuscribe, que es peor que no tener feed.
  2. Eventos de dia completo: un vencimiento no ocurre a las 3 de la manana.
  3. VALARM dentro del evento: el calendario avisa por su cuenta aunque el
     servidor este apagado.
  4. Lo cumplido desaparece: si no, el feed se vuelve un archivo historico.

Que lleva el feed: el titulo de la obligacion tal como se ve en pantalla, su
fecha y su importe. Nunca el contenido de un documento ni el saldo de una
cuenta. Aun asi, un titulo puede llevar datos que alguien no quiera publicar
-"Tarjeta ****9876"-, y el token viaja en una URL, que es un secreto debil.
Para eso esta el modo discreto: el evento dice solo el area ("Seguro",
"Vehiculo") y nada mas.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re

from django.conf import settings

from ..models import Obligation
from ..scoping import use_household

PRODID = "-//Lares//Obligaciones//ES"
MAX_OCTETS = 75


def _escape(texto: str) -> str:
    """RFC 5545: la coma, el punto y coma y la barra se escapan."""
    return (
        str(texto)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(linea: str) -> str:
    """Plegado a 75 octetos. Sin esto, algunos clientes truncan en silencio."""
    crudo = linea.encode("utf-8")
    if len(crudo) <= MAX_OCTETS:
        return linea

    trozos, actual = [], b""
    for caracter in linea:
        codificado = caracter.encode("utf-8")
        limite = MAX_OCTETS if not trozos else MAX_OCTETS - 1
        if len(actual) + len(codificado) > limite:
            trozos.append(actual.decode("utf-8"))
            actual = b""
        actual += codificado
    trozos.append(actual.decode("utf-8"))
    return "\r\n ".join(trozos)


def _uid(obligation) -> str:
    """Estable mientras la obligación sea la misma, aunque cambie su fecha."""
    limpio = re.sub(r"[^A-Za-z0-9:._-]", "", obligation.dedupe_key)[:120]
    if not limpio:
        limpio = hashlib.sha256(obligation.dedupe_key.encode()).hexdigest()[:32]
    return f"{limpio}@lares.local"


def _sequence(obligation) -> int:
    """Sube cuando la obligación cambia, para que el cliente acepte la nueva versión."""
    return (obligation.updated_at.date() - dt.date(2020, 1, 1)).days


AREAS = {
    "vehicles": "Vehículo", "property": "Inmueble", "insurance": "Seguro",
    "finance": "Dinero", "belongings": "Objeto", "maintenance": "Mantenimiento",
    "packs": "Trámite", "core": "Documento",
}


def _area(obligation) -> str:
    raiz = (obligation.source or "").split(".")[0]
    return AREAS.get(raiz, "Vencimiento")


def _event(obligation, today: dt.date, discreet: bool = False) -> list[str]:
    fin = obligation.due_on + dt.timedelta(days=1)

    if discreet:
        # Solo el área. Sirve para saber que hay algo, sin publicar qué.
        resumen = _area(obligation)
        descripcion = [f"Abre {settings.PRODUCT_NAME} para ver el detalle."]
    else:
        resumen = obligation.title
        if obligation.amount:
            resumen = f"{resumen} · {obligation.amount:,.0f} {obligation.currency}".rstrip()

        descripcion = []
        if obligation.counterparty:
            descripcion.append(f"Con: {obligation.counterparty}")
        if obligation.subject:
            descripcion.append(f"Sobre: {obligation.subject}")
        descripcion.append(f"Generado por {settings.PRODUCT_NAME}")

    lineas = [
        "BEGIN:VEVENT",
        f"UID:{_uid(obligation)}",
        f"SEQUENCE:{_sequence(obligation)}",
        f"DTSTAMP:{obligation.updated_at:%Y%m%dT%H%M%SZ}",
        f"DTSTART;VALUE=DATE:{obligation.due_on:%Y%m%d}",
        f"DTEND;VALUE=DATE:{fin:%Y%m%d}",
        f"SUMMARY:{_escape(resumen)}",
        f"DESCRIPTION:{_escape(chr(10).join(descripcion))}",
        "TRANSP:TRANSPARENT",
        f"CATEGORIES:{_escape(obligation.source or 'lares')}",
    ]
    if obligation.severity in ("high", "critical"):
        lineas.append("PRIORITY:1")

    # Los mismos plazos con los que avisa Lares: el calendario avisa solo.
    for offset in sorted(obligation.remind_offsets or [], reverse=True):
        dias = abs(int(offset))
        if dias and obligation.due_on - dt.timedelta(days=dias) >= today:
            lineas += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"TRIGGER:-P{dias}D",
                f"DESCRIPTION:{_escape(resumen)}",
                "END:VALARM",
            ]
    lineas.append("END:VEVENT")
    return lineas


def feed(household, source_prefix: str = "", horizon_days: int = 730,
         discreet: bool = False) -> str:
    """Todo lo pendiente, como calendario. Lo cumplido no sale."""
    hoy = dt.date.today()
    nombre = household.name
    if source_prefix:
        nombre = f"{nombre} · {source_prefix}"

    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(nombre)}",
        "X-WR-TIMEZONE:" + household.timezone,
        # Google refresca cuando quiere, pero pedirlo no cuesta nada.
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]

    with use_household(household):
        qs = Obligation.objects.filter(
            status__in=[Obligation.Status.PENDING, Obligation.Status.OVERDUE],
            due_on__lte=hoy + dt.timedelta(days=horizon_days),
        ).select_related("counterparty")
        if source_prefix:
            qs = qs.filter(source__startswith=source_prefix)

        for obligation in qs:
            lineas += _event(obligation, hoy, discreet=discreet)

    lineas.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lineas) + "\r\n"


def single(obligation) -> str:
    """Una obligación suelta, para el botón «añadir al calendario»."""
    hoy = dt.date.today()
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    lineas += _event(obligation, hoy)
    lineas.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lineas) + "\r\n"
