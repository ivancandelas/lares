"""Manejadores del nucleo sobre el bus de eventos."""

from django.db import transaction
from django.dispatch import receiver

from .models import Event, lares_event


@receiver(lares_event)
def persist_event(sender, household, verb, subject=None, payload=None, actor=None,
                  summary="", source="", **kwargs):
    """Todo evento emitido queda en la linea de tiempo. Sin excepciones."""
    if household is None:
        return
    Event.objects.create(
        household=household,
        verb=verb,
        source=source or (sender if isinstance(sender, str) else ""),
        actor=actor,
        subject=subject,
        summary=summary,
        payload=payload or {},
    )


@receiver(lares_event)
def notify_webhooks(sender, household, verb, subject=None, payload=None,
                    summary="", **kwargs):
    """Avisa fuera de la instalación.

    Se hace después de confirmar la transacción: enviar un webhook sobre algo
    que luego se deshace deja al receptor con una versión de los hechos que
    aquí nunca ocurrió.
    """
    if household is None:
        return

    from .tasks import dispatch_webhooks

    datos = {"subject": str(getattr(subject, "pk", "")) or None,
             "summary": summary, **(payload or {})}
    transaction.on_commit(
        lambda: dispatch_webhooks.delay(str(household.pk), verb, datos)
    )
