"""El cargo recurrente y el fin de la permanencia."""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec
from lares.core.schedule import next_occurrences

MESES = {"monthly": 1, "quarterly": 3, "semiannual": 6, "yearly": 12}


class ChargeProvider(ObligationProvider):
    """Que el cargo aparezca antes de llegar, no después en el estado de cuenta."""

    key = "subscriptions.charge"
    label = "Cargo de suscripción"
    applies_to = "subscription"

    def generate(self, sub, on_date: dt.date):
        if not sub.charge_day or sub.cycle == sub.Cycle.WEEKLY:
            return []
        meses = MESES.get(sub.cycle, 1)
        if meses == 1:
            calendario = {"monthly": {"day": sub.charge_day}}
        else:
            inicio = on_date.replace(day=min(sub.charge_day, 28))
            calendario = {"every": {"months": meses}, "from": inicio.isoformat()}

        return [
            ObligationSpec(
                dedupe_key=f"sub:{sub.pk}:charge:{due:%Y-%m}",
                title=f"{sub.name}",
                due_on=due,
                amount=sub.amount,
                currency=sub.currency or None,
                counterparty=sub.provider,
                severity="low",
                # Avisar dos días antes basta: no hay que hacer nada, solo saber.
                remind_offsets=(-2,),
            )
            for due in next_occurrences(calendario, on_date, count=2)
        ]


class CommitmentProvider(ObligationProvider):
    """Cuando acaba la permanencia es el único momento con poder de negociación."""

    key = "subscriptions.commitment"
    label = "Fin de permanencia"
    applies_to = "subscription"

    def generate(self, sub, on_date: dt.date):
        if not sub.commitment_until or sub.commitment_until < on_date:
            return []
        return [ObligationSpec(
            dedupe_key=f"sub:{sub.pk}:commitment:{sub.commitment_until:%Y-%m-%d}",
            title=f"Acaba la permanencia de {sub.name}",
            due_on=sub.commitment_until,
            amount=sub.yearly_cost,
            currency=sub.currency or None,
            counterparty=sub.provider,
            severity="normal",
            remind_offsets=(-45, -15, -1),
        )]
