"""Cobrar es tan obligacion como pagar.

La diferencia esta en quien te lo recuerda: cuando debes, llega un recibo;
cuando te deben, no llega nada. Por eso el aviso de cobro importa mas.
"""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec
from lares.core.schedule import next_occurrences

from .models import Loan


class PaymentProvider(ObligationProvider):
    key = "loans.payment"
    label = "Cuota de préstamo"
    applies_to = "loan"

    def generate(self, loan, on_date: dt.date):
        if loan.is_settled or not (loan.payment_day and loan.payment_amount):
            return []
        if loan.state in (Loan.State.PAID, Loan.State.FORGIVEN):
            return []

        cobrar = loan.is_mine_to_collect
        return [
            ObligationSpec(
                dedupe_key=f"loan:{loan.pk}:{due:%Y-%m}",
                title=(f"Cobrar de {loan.name}" if cobrar else f"Pagar {loan.name}"),
                due_on=due,
                amount=min(loan.payment_amount, loan.outstanding),
                currency=loan.currency or None,
                counterparty=loan.counterpart,
                # Dejar de pagar tiene consecuencias inmediatas; dejar de cobrar
                # solo se nota cuando ya pasó un año.
                severity="high" if not cobrar else "normal",
                remind_offsets=(-7, -2) if not cobrar else (-5,),
                payload={"direction": loan.direction},
            )
            for due in next_occurrences(
                {"monthly": {"day": loan.payment_day}}, on_date, count=2
            )
        ]
