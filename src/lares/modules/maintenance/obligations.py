"""Un plan de mantenimiento genera su proximo aviso."""

import datetime as dt

from dateutil.relativedelta import relativedelta

from lares.core.registry import ObligationProvider, ObligationSpec

from .models import MaintenancePlan


class MaintenanceProvider(ObligationProvider):
    """Solo por tiempo.

    El mantenimiento por kilómetros lo calcula cada módulo, porque solo él sabe
    leer su propio odómetro: el núcleo no tiene por qué saber qué es un coche.
    """

    key = "maintenance.plan"
    label = "Mantenimiento programado"
    applies_to = "maintenance_plan"

    def generate(self, plan, on_date: dt.date):
        if plan.basis != MaintenancePlan.Basis.TIME or not plan.every_months:
            return []

        base = plan.last_done_on or on_date
        due = base + relativedelta(months=plan.every_months)
        # Si se pasó hace tiempo, el aviso es hoy: arrastrarlo al pasado lo
        # dejaría escondido entre lo vencido antiguo.
        if due < on_date:
            due = on_date

        return [ObligationSpec(
            dedupe_key=f"plan:{plan.pk}:{due:%Y-%m}",
            title=f"{plan.title}, {plan.subject}",
            due_on=due,
            amount=plan.estimated_cost,
            counterparty=plan.preferred_provider,
            severity="normal",
            remind_offsets=(-21, -7, -1),
        )]
