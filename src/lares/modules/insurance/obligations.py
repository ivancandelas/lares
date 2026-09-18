"""Renovacion y prima: las dos fechas que cuestan dinero si se pasan."""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec
from lares.core.schedule import next_occurrences

MESES = {"yearly": 12, "semiannual": 6, "quarterly": 3, "monthly": 1}


class RenewalProvider(ObligationProvider):
    """Renovar tarde deja un hueco de cobertura, no solo un trámite pendiente."""

    key = "insurance.renewal"
    label = "Renovación de póliza"
    applies_to = "policy"

    def generate(self, policy, on_date: dt.date):
        if not policy.ends_on or policy.ends_on < on_date:
            return []
        return [ObligationSpec(
            dedupe_key=f"policy:{policy.pk}:renewal:{policy.ends_on:%Y-%m-%d}",
            title=f"Renovar {policy.name}",
            due_on=policy.ends_on,
            amount=policy.premium,
            currency=policy.currency or None,
            counterparty=policy.insurer,
            severity="critical",
            # Comparar otras opciones lleva semanas, no días.
            remind_offsets=(-45, -30, -15, -7, -1),
        )]


class PremiumProvider(ObligationProvider):
    """Primas fraccionadas: dejar de pagar una cancela la póliza entera."""

    key = "insurance.premium"
    label = "Pago de prima"
    applies_to = "policy"

    def generate(self, policy, on_date: dt.date):
        if policy.premium_cycle == "yearly" or not policy.premium_day:
            return []            # la anual ya va en la renovación
        meses = MESES.get(policy.premium_cycle, 1)
        if meses == 1:
            calendario = {"monthly": {"day": policy.premium_day}}
        else:
            inicio = on_date.replace(day=min(policy.premium_day, 28))
            calendario = {"every": {"months": meses}, "from": inicio.isoformat()}

        return [
            ObligationSpec(
                dedupe_key=f"policy:{policy.pk}:premium:{due:%Y-%m}",
                title=f"Prima de {policy.name}",
                due_on=due,
                amount=policy.premium,
                currency=policy.currency or None,
                counterparty=policy.insurer,
                severity="high",
                remind_offsets=(-7, -2),
            )
            for due in next_occurrences(calendario, on_date, count=2)
        ]
