"""Entrega de webhooks.

Cada envio va firmado con HMAC-SHA256 sobre el cuerpo exacto, para que quien lo
recibe pueda comprobar que viene de esta instalacion y que nadie lo modifico por
el camino. Sin firma, un endpoint publico acepta cualquier cosa.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request

from django.utils import timezone

from ..models import Webhook, WebhookDelivery

logger = logging.getLogger(__name__)

TIMEOUT = 10


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def deliver(household, verb: str, payload: dict) -> list:
    """Envia el evento a los webhooks suscritos. Devuelve las entregas."""
    entregas = []
    for hook in Webhook.all_objects.filter(household=household, is_active=True):
        if not hook.wants(verb):
            continue
        entregas.append(_send(household, hook, verb, payload))
    return entregas


def _send(household, hook, verb, payload):
    body = json.dumps(
        {"event": verb, "household": str(household.pk),
         "at": timezone.now().isoformat(), "data": payload},
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        hook.url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Lares-Event": verb,
            "X-Lares-Signature": sign(hook.secret, body),
        },
    )

    delivery = WebhookDelivery(household=household, webhook=hook, verb=verb)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            delivery.status_code = response.status
    except urllib.error.HTTPError as exc:
        delivery.status_code = exc.code
        delivery.error = str(exc)[:300]
    except Exception as exc:
        # Que un endpoint externo este caido no puede tumbar la operacion que
        # genero el evento.
        delivery.error = str(exc)[:300]
        logger.warning("Webhook %s falló: %s", hook.url, exc)
    delivery.save()
    return delivery
