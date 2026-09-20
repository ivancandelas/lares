"""Hablar con Paperless-ngx.

La regla del producto, que estaba escrita mucho antes que este archivo:
**Paperless sabe qué es el documento; Lares sabe por qué importa.** De ahí que
aquí no se copie nada. Lares guarda `paperless:<id>` y va a buscar el binario
cuando de verdad hace falta verlo.

Lo que sí se trae es el **texto ya reconocido**: repetir el OCR sería una
dependencia binaria más para llegar al mismo sitio, y peor.

Dos cosas que este módulo se toma en serio:

  - **Que Paperless no responda no puede tumbar Lares.** El documento sigue
    existiendo aquí con sus fechas, sus importes y sus avisos; lo único que
    falla es abrir el PDF, y eso se dice con esas palabras.
  - **El token no sale de aquí.** Lo que ve quien abre un enlace compartido o
    un paquete de sucesión pasa por Lares, no por Paperless: repartir la
    dirección y el token de Paperless para ver una factura es regalar el
    archivo entero.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

PREFIJO = "paperless:"
TIMEOUT = 30


class Inalcanzable(Exception):
    """Paperless no contestó, o contestó que no."""


def doc_id(ref: str) -> str:
    """El identificador dentro de Paperless, si la referencia es suya."""
    ref = ref or ""
    return ref[len(PREFIJO):] if ref.startswith(PREFIJO) else ""


def connector_for(household):
    from ..models import Connector

    return Connector.all_objects.filter(
        household=household, key="paperless", is_active=True
    ).first()


def base_of(household) -> str:
    conector = connector_for(household)
    if not conector:
        return ""
    return (conector.config.get("base_url") or "").rstrip("/")


def url_for(household, ref: str) -> str:
    """La dirección para abrirlo en Paperless, tal y como la teclearía alguien."""
    identificador = doc_id(ref)
    base = base_of(household)
    if not (identificador and base):
        return ""
    return f"{base}/documents/{identificador}/details"


def fetch(household, ref: str, kind: str = "preview") -> tuple[bytes, str]:
    """Trae el archivo de Paperless. Devuelve (bytes, tipo de contenido).

    `kind` es "preview" para verlo y "download" para guardarlo: Paperless
    sirve el archivo archivado en el primero y el original en el segundo.
    """
    identificador = doc_id(ref)
    conector = connector_for(household)
    if not (identificador and conector):
        raise Inalcanzable("Este documento no viene de Paperless.")

    base = (conector.config.get("base_url") or "").rstrip("/")
    token = conector.secret
    if not (base and token):
        raise Inalcanzable("El conector de Paperless está sin configurar.")

    url = f"{base}/api/documents/{identificador}/{kind}/"
    try:
        peticion = urllib.request.Request(
            url, headers={"Authorization": f"Token {token}"})
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:  # noqa: S310
            return respuesta.read(), respuesta.headers.get_content_type()
    except Exception as exc:
        logger.warning("Paperless no sirvió el documento %s: %s", ref, exc)
        raise Inalcanzable(str(exc)[:200]) from exc


def metadata(household, identificador) -> dict:
    """Los metadatos de un documento: título, texto reconocido, fechas."""
    conector = connector_for(household)
    if not conector:
        raise Inalcanzable("No hay conector de Paperless en este hogar.")

    base = (conector.config.get("base_url") or "").rstrip("/")
    token = conector.secret
    if not (base and token):
        raise Inalcanzable("El conector de Paperless está sin configurar.")

    url = f"{base}/api/documents/{urllib.parse.quote(str(identificador))}/"
    try:
        peticion = urllib.request.Request(
            url, headers={"Authorization": f"Token {token}"})
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:  # noqa: S310
            return json.loads(respuesta.read())
    except Exception as exc:
        raise Inalcanzable(str(exc)[:200]) from exc


def annotate_links(household, documentos) -> list:
    """Pone `external_url` en cada documento que viva en Paperless.

    Se resuelve el conector una sola vez para toda la lista: preguntarlo
    documento a documento sería un N+1 en la pantalla que más documentos tiene.
    """
    documentos = list(documentos)
    base = base_of(household) if documentos else ""
    for doc in documentos:
        identificador = doc_id(getattr(doc, "external_ref", ""))
        doc.external_url = (f"{base}/documents/{identificador}/details"
                            if base and identificador else "")
    return documentos


# ---------------------------------------------------------------------------
# La vuelta: que desde Paperless se llegue a Lares
# ---------------------------------------------------------------------------


def write_back(household, ref: str, url: str, campo: str = "lares_url") -> bool:
    """Deja en Paperless un campo con el enlace a Lares.

    Sin esto la navegacion es de ida y no de vuelta: quien esta mirando un PDF
    en Paperless no tiene forma de saber que en Lares ese papel es la poliza
    del coche, con su vencimiento y su aviso.

    Es **opcional y silencioso**: si el campo no existe o el token no tiene
    permiso de escritura, no pasa nada. Que la vuelta no funcione no puede
    impedir registrar un documento.
    """
    identificador = doc_id(ref)
    conector = connector_for(household)
    if not (identificador and conector and url):
        return False
    if not conector.config.get("write_back"):
        return False

    base = (conector.config.get("base_url") or "").rstrip("/")
    token = conector.secret
    if not (base and token):
        return False

    try:
        campo_id = _custom_field_id(base, token, campo)
        if campo_id is None:
            return False
        cuerpo = json.dumps({
            "custom_fields": [{"field": campo_id, "value": url}],
        }).encode()
        peticion = urllib.request.Request(
            f"{base}/api/documents/{identificador}/", data=cuerpo, method="PATCH",
            headers={"Authorization": f"Token {token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(peticion, timeout=TIMEOUT):  # noqa: S310
            return True
    except Exception as exc:
        logger.info("No se pudo escribir de vuelta en Paperless (%s): %s", ref, exc)
        return False


def _custom_field_id(base: str, token: str, nombre: str):
    """El id del campo personalizado, que hay que crear a mano en Paperless."""
    url = f"{base}/api/custom_fields/?name__iexact={urllib.parse.quote(nombre)}"
    peticion = urllib.request.Request(
        url, headers={"Authorization": f"Token {token}"})
    with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:  # noqa: S310
        datos = json.loads(respuesta.read())
    resultados = datos.get("results") or []
    return resultados[0]["id"] if resultados else None


# ---------------------------------------------------------------------------
# Materializar: cuando el archivo tiene que sobrevivir fuera
# ---------------------------------------------------------------------------


def materialize(household, documento) -> bytes | None:
    """Los bytes de un documento referenciado, para meterlos en un paquete.

    Referenciar es lo correcto en el dia a dia -una sola verdad, sin duplicar
    gigas- pero choca con dos promesas del producto: la exportacion total es
    «la prueba de que los datos son del usuario», y el paquete de sucesion
    existe para sobrevivir a la instalacion. Si el PDF solo vive en Paperless,
    el dia que alguien abra ese paquete no hay escrituras que abrir.

    Asi que se referencia siempre y se materializa cuando hace falta que el
    archivo salga de aqui. Devuelve None si Paperless no contesta: un paquete
    incompleto vale mas que un paquete que no se genera.
    """
    if getattr(documento, "file", None):
        return None
    if not doc_id(getattr(documento, "external_ref", "")):
        return None
    try:
        contenido, _ = fetch(household, documento.external_ref, kind="download")
        return contenido
    except Inalcanzable:
        return None


def filename_for(documento) -> str:
    identificador = doc_id(documento.external_ref)
    nombre = (documento.title or f"paperless-{identificador}").replace("/", "-")
    return f"{nombre}.pdf" if not nombre.lower().endswith(".pdf") else nombre
