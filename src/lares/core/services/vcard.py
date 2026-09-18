"""Exportacion de contactos en vCard.

vCard 4.0 (RFC 6350) es el unico formato que entienden a la vez el telefono, el
ordenador y el correo. Exportar en el formato de nadie ata los contactos a este
programa, que es justo lo contrario de lo que promete.

Se puede exportar una persona o una etiqueta entera: "mandale a mi hijo todos
los de familia" es una operacion, no treinta.
"""

from __future__ import annotations

from ..models import ContactPoint

MAX_OCTETS = 75


def _escape(texto: str) -> str:
    return (
        str(texto)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(linea: str) -> str:
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


TIPOS = {
    ContactPoint.Channel.PHONE: ("TEL", "voice"),
    ContactPoint.Channel.EMAIL: ("EMAIL", ""),
    ContactPoint.Channel.ADDRESS: ("ADR", "home"),
    ContactPoint.Channel.WEB: ("URL", ""),
}


def card(party, tags: list | None = None) -> list[str]:
    from ..models.tagging import tags_of

    etiquetas = tags if tags is not None else tags_of(party)
    lineas = [
        "BEGIN:VCARD",
        "VERSION:4.0",
        f"UID:urn:uuid:{party.pk}",
        f"FN:{_escape(party.name)}",
        # N es obligatorio en vCard 4: se deja el apellido vacío antes que
        # inventar una division que el usuario no escribio.
        f"N:;{_escape(party.name)};;;",
    ]
    if party.kind == party.Kind.ORGANIZATION:
        lineas.append("KIND:org")
        lineas.append(f"ORG:{_escape(party.name)}")

    for punto in party.contact_points.all():
        prop, tipo = TIPOS.get(punto.channel, ("NOTE", ""))
        params = []
        if tipo:
            params.append(f"TYPE={tipo}")
        if punto.is_primary:
            params.append("PREF=1")
        cabecera = prop + ("".join(f";{p}" for p in params))
        valor = punto.value
        if prop == "ADR":
            # ADR tiene siete campos; solo se rellena la calle.
            valor = f";;{_escape(valor)};;;;"
            lineas.append(f"{cabecera}:{valor}")
            continue
        if prop == "TEL":
            cabecera += ";VALUE=text"
        lineas.append(f"{cabecera}:{_escape(valor)}")

    if party.birth_date:
        lineas.append(f"BDAY:{party.birth_date:%Y%m%d}")
    if party.tax_id:
        lineas.append(f"NOTE:RFC {_escape(party.tax_id)}")
    for etiqueta in etiquetas:
        lineas.append(f"CATEGORIES:{_escape(etiqueta.name)}")

    lineas.append("END:VCARD")
    return lineas


def export(parties) -> str:
    lineas = []
    for party in parties:
        lineas += card(party)
    return "\r\n".join(_fold(x) for x in lineas) + "\r\n"
