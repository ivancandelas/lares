"""Tareas programadas del nucleo.

Todas son idempotentes: se pueden reintentar sin efectos secundarios.
"""

from celery import shared_task

from .models import Household
from .services import checks, notify, obligations


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
