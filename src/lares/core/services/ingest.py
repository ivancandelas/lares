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
