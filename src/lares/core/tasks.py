"""Tareas programadas del nucleo.

Todas son idempotentes: se pueden reintentar sin efectos secundarios.
"""

from celery import shared_task

from .models import Household
from .services import obligations


@shared_task
def materialize_obligations():
    results = {}
    for household in Household.objects.all():
        obligations.mark_overdue(household)
        results[str(household.pk)] = obligations.materialize(household)
    return results


@shared_task
def run_checks():
    from .services import checks

    return {
        str(h.pk): len(checks.run_all(h))
        for h in Household.objects.all()
    }
