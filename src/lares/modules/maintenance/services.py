"""Consultas del historial.

Responden las dos preguntas por las que existe el modulo: quien hizo aquello y
cuanto llevo gastado en esto.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max, Sum

from .models import WorkOrder


def history_for(resource) -> list:
    concreto = resource.as_concrete()
    return list(
        WorkOrder.objects.filter(
            subject_type=ContentType.objects.get_for_model(concreto.__class__),
            subject_id=concreto.pk,
        ).select_related("provider")
    )


def spent_on(resource):
    return sum(w.cost or 0 for w in history_for(resource))


def providers(household) -> list:
    """Quién ha trabajado para ti, cuántas veces y por cuánto."""
    datos = (
        WorkOrder.objects.exclude(provider__isnull=True)
        .values("provider_id", "provider__name")
        .annotate(trabajos=Count("id"), total=Sum("cost"), ultimo=Max("done_on"))
        .order_by("-ultimo")
    )
    return list(datos)
