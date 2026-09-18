"""Manejadores del nucleo sobre el bus de eventos."""

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
