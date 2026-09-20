"""La agenda: lo que alimenta la pantalla 'Esta semana'."""

from __future__ import annotations

import datetime as dt

from ..models import Obligation
from ..scoping import use_household


# Un ano de horizonte: casi todo lo que administra un hogar es anual
# (refrendo, verificacion, polizas, predial). Ver menos oculta justo lo
# que el sistema existe para anticipar.
def week_ahead(household, horizon_days: int = 365) -> dict:
    today = dt.date.today()
    with use_household(household):
        pending = Obligation.objects.filter(
            status__in=[Obligation.Status.PENDING, Obligation.Status.OVERDUE],
            due_on__lte=today + dt.timedelta(days=horizon_days),
        ).select_related("counterparty", "assigned_to")

        # De quién es cada una. Se resuelve en bloque -dos consultas fijas- y
        # no fila a fila, que seria un N+1 que crece con los datos.
        from .responsibilities import annotate, responsible_map

        pending = annotate(list(pending), responsible_map(household))

        overdue = [o for o in pending if o.due_on < today]
        this_week = [o for o in pending if today <= o.due_on <= today + dt.timedelta(days=7)]
        later = [o for o in pending if o.due_on > today + dt.timedelta(days=7)]

    return {
        "today": today,
        "overdue": overdue,
        "this_week": this_week,
        "later": later,
        "total_amount": sum(o.amount or 0 for o in pending),
    }
