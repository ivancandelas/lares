"""Pipeline de la bandeja: recibir, extraer, proponer.

    entra un archivo
        -> InboxItem crudo e inmutable (deduplicado por checksum)
        -> se extrae texto si se puede
        -> los clasificadores proponen
        -> la persona confirma  <- siempre

Lo ultimo no es una cortesia: es lo que mantiene separable lo verificado de lo
adivinado. Sin ese paso, nadie puede fiarse de nada de lo que hay dentro.
"""

from __future__ import annotations

import hashlib
import io
import logging

from django.db import transaction

from ..models import Document, InboxItem, Party, Suggestion, lares_event
from ..registry import registry

logger = logging.getLogger(__name__)

MAX_TEXT = 20000


@transaction.atomic
def receive(household, uploaded, source=InboxItem.Source.UPLOAD, note="") -> tuple:
    """Mete un archivo en la bandeja. Devuelve (item, es_nuevo)."""
    contenido = uploaded.read()
    uploaded.seek(0)
    checksum = hashlib.sha256(contenido).hexdigest()

    existente = InboxItem.all_objects.filter(
        household=household, checksum=checksum
    ).first()
    if existente:
        # Reenviar el mismo correo dos veces no debe crear nada dos veces.
        return existente, False

    item = InboxItem.objects.create(
        household=household,
        source=source,
        original_name=getattr(uploaded, "name", "")[:300],
        mime_type=getattr(uploaded, "content_type", "") or "",
        size_bytes=len(contenido),
        checksum=checksum,
        note=note,
    )
    item.file.save(item.original_name or f"{item.pk}", uploaded, save=True)

    item.text = extract_text(contenido, item.original_name, item.mime_type)
    item.save(update_fields=["text", "updated_at"])

    classify(item)
    lares_event.send(sender="ingest", household=household, verb="inbox.received",
                     subject=item, summary=item.original_name, payload={})
    return item, True


@transaction.atomic
def receive_reference(household, ref: str, name: str, text: str = "",
                      source=InboxItem.Source.PAPERLESS, note: str = "",
                      mime: str = "") -> tuple:
    """Mete en la bandeja algo cuyo archivo vive fuera. Devuelve (item, es_nuevo).

    Lares no copia el binario de Paperless: guarda la referencia y el texto que
    Paperless ya reconocio. Duplicarlo dejaria dos repositorios documentales sin
    que nadie lo hubiera decidido, y el doble de gigas para el mismo PDF.

    La identidad de lo referenciado **es la referencia**, no sus bytes -que a
    proposito no tenemos-, asi que el checksum se calcula sobre ella. Es lo que
    hace idempotente un webhook que se repite.
    """
    if not ref:
        raise ValueError("Una entrada por referencia necesita su referencia.")

    checksum = hashlib.sha256(ref.encode()).hexdigest()
    existente = InboxItem.all_objects.filter(
        household=household, external_ref=ref
    ).first()
    if existente:
        return existente, False

    item = InboxItem.objects.create(
        household=household, source=source,
        original_name=(name or ref)[:300],
        mime_type=mime, checksum=checksum, external_ref=ref, note=note,
        text=(text or "")[:MAX_TEXT],
    )
    classify(item)
    lares_event.send(sender="ingest", household=household, verb="inbox.received",
                     subject=item, summary=item.original_name,
                     payload={"external_ref": ref})
    return item, True


def extract_text(contenido: bytes, name: str = "", mime: str = "") -> str:
    """Texto plano de lo que se pueda leer sin OCR.

    Un PDF escaneado no tiene capa de texto y aquí devuelve vacío. Ese es
    justamente el hueco que cubre el conector de Paperless, que ya hace OCR:
    no tiene sentido duplicarlo aquí.
    """
    nombre = (name or "").lower()
    if nombre.endswith((".txt", ".xml", ".csv", ".json")) or "xml" in mime or "text" in mime:
        return contenido.decode("utf-8", errors="replace")[:MAX_TEXT]

    if nombre.endswith(".pdf") or "pdf" in mime:
        try:
            from pypdf import PdfReader

            lector = PdfReader(io.BytesIO(contenido))
            paginas = [(p.extract_text() or "") for p in lector.pages[:20]]
            return "\n".join(paginas)[:MAX_TEXT]
        except Exception:
            logger.info("No se pudo extraer texto del PDF %s", name)
    return ""


def classify(item) -> list:
    """Pasa el item por todos los clasificadores. Guarda lo que propongan."""
    propuestas = []
    for classifier in registry.classifiers:
        try:
            propuesta = classifier.classify(item)
        except Exception:
            logger.exception("El clasificador %s falló", classifier.key)
            continue
        if not propuesta:
            continue
        propuestas.append(Suggestion.objects.create(
            household=item.household, item=item, classifier=classifier.key,
            label=propuesta.label, confidence=propuesta.confidence,
            plan=propuesta.plan,
        ))
    return propuestas


def reclassify(item) -> list:
    """Vuelve a pasar un item por los clasificadores.

    Es la razon por la que el crudo se conserva siempre. Cuando se anade un
    clasificador nuevo -o se corrige uno- lo que entro mal tiene que poder
    volver a entrar bien, sin pedirle al usuario que suba nada otra vez.
    """
    item.suggestions.all().delete()
    if item.file and not item.text:
        try:
            with item.file.open("rb") as fh:
                item.text = extract_text(fh.read(), item.original_name, item.mime_type)
            item.save(update_fields=["text", "updated_at"])
        except (FileNotFoundError, ValueError):
            logger.info("No se pudo releer el archivo de %s", item.pk)
    return classify(item)


def reclassify_all(household, only_pending: bool = True) -> dict:
    """Reprocesa la bandeja entera. Nunca toca lo ya registrado."""
    from ..models import InboxItem as _InboxItem

    qs = _InboxItem.objects.all()
    if only_pending:
        qs = qs.filter(status=_InboxItem.Status.NEW)
    else:
        # Lo aplicado se queda como está: ya lo confirmó una persona.
        qs = qs.exclude(status=_InboxItem.Status.APPLIED)

    revisados = reconocidos = 0
    for item in qs:
        revisados += 1
        reconocidos += bool(reclassify(item))
    return {"reviewed": revisados, "recognised": reconocidos}


def initial_document_data(item) -> dict:
    """Los valores con los que llega precargado el formulario de la persona."""
    propuesta = item.suggestion
    if not propuesta:
        return {"title": (item.original_name or "").rsplit(".", 1)[0]}

    datos = dict(propuesta.plan.get("document") or {})
    datos.setdefault("title", propuesta.label)
    return {k: v for k, v in datos.items() if v not in (None, "")}


@transaction.atomic
def apply(item, document: Document) -> InboxItem:
    """Cierra un item de la bandeja tras confirmar la persona."""
    party_plan = (item.suggestion.plan.get("party") if item.suggestion else None)
    if party_plan and not document.issuer_id and party_plan.get("name"):
        emisor, _ = Party.objects.get_or_create(
            household=item.household,
            tax_id=party_plan.get("tax_id", ""),
            name=party_plan["name"],
            defaults={"kind": party_plan.get("kind", Party.Kind.ORGANIZATION)},
        )
        document.issuer = emisor
        document.save(update_fields=["issuer", "updated_at"])

    if item.external_ref and not document.external_ref:
        # Sin esto, el enlace con Paperless se perdía justo al confirmar, que
        # es el momento en que empieza a valer para algo.
        document.external_ref = item.external_ref
        document.save(update_fields=["external_ref", "updated_at"])
        _devolver_el_enlace(document)

    item.status = InboxItem.Status.APPLIED
    item.applied_document = document
    item.save(update_fields=["status", "applied_document", "updated_at"])

    lares_event.send(sender="ingest", household=item.household,
                     verb="document.classified", subject=document,
                     summary=document.title,
                     payload={"doc_type": document.doc_type, "inbox": str(item.pk)})
    return item


def discard(item) -> InboxItem:
    """Descartar no borra: el archivo crudo se conserva para reprocesarlo."""
    item.status = InboxItem.Status.DISCARDED
    item.save(update_fields=["status", "updated_at"])
    return item


def _devolver_el_enlace(document) -> None:
    """Deja en Paperless un enlace de vuelta a Lares, si está configurado.

    Va después de confirmar y nunca antes: hasta que una persona no dice qué
    es el documento, en Lares no hay nada a lo que apuntar.
    """
    from django.conf import settings

    from . import paperless

    try:
        url = f"{settings.SITE_URL.rstrip('/')}/documentos/{document.pk}/editar/"
        paperless.write_back(document.household, document.external_ref, url)
    except Exception:
        # La vuelta es una comodidad: que falle no puede impedir registrar.
        logger.info("No se pudo escribir la vuelta en Paperless", exc_info=True)
