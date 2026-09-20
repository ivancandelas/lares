"""Tareas programadas del nucleo.

Todas son idempotentes: se pueden reintentar sin efectos secundarios.
"""

from celery import shared_task

from .connectors import run_connector
from .models import Connector, Household
from .services import checks, notify, obligations, succession, webhooks


@shared_task
def materialize_obligations():
    results = {}
    for household in Household.objects.all():
        obligations.mark_overdue(household)
        results[str(household.pk)] = obligations.materialize(household)
    return results


@shared_task
def send_reminders():
    return {
        str(h.pk): notify.send_due_reminders(h)
        for h in Household.objects.all()
    }


@shared_task
def run_checks():
    return {
        str(h.pk): len(checks.run_all(h))
        for h in Household.objects.all()
    }


@shared_task
def dispatch_webhooks(household_id, verb, payload):
    household = Household.objects.filter(pk=household_id).first()
    if not household:
        return {"delivered": 0}
    entregas = webhooks.deliver(household, verb, payload)
    return {"delivered": sum(1 for e in entregas if e.ok), "attempted": len(entregas)}


@shared_task
def poll_connectors():
    """Trae lo que haya en Paperless, el buzón y las carpetas vigiladas."""
    total = {}
    for connector in Connector.all_objects.filter(is_active=True):
        result = run_connector(connector)
        total[str(connector.pk)] = {"new": result.new, "error": result.error}
    return total


@shared_task
def review_succession():
    """Avisa, libera o rearma los accesos diferidos.

    Es idempotente como las demas: lo que decide son dias de silencio, asi que
    correrla dos veces el mismo dia no adelanta ni repite nada.
    """
    return {
        str(h.pk): succession.review(h)
        for h in Household.objects.all()
    }
