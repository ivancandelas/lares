"""El pago de una tarjeta es una obligacion como cualquier otra.

Con una diferencia que importa: no pagarla a tiempo cuesta dinero de inmediato,
asi que la severidad es alta y los avisos son cortos y repetidos, no largos.
"""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec
from lares.core.schedule import next_occurrences


class CardPaymentProvider(ObligationProvider):
    key = "finance.card_payment"
    label = "Pago de tarjeta"
    applies_to = "credit_card"

    def generate(self, card, on_date: dt.date):
        if not card.due_day:
            return []
        saldo = card.account.balance if card.account else None
        return [
            ObligationSpec(
                dedupe_key=f"card:{card.pk}:payment:{due:%Y-%m}",
                title=f"Pago de {card}",
                due_on=due,
                severity="high",
                amount=saldo if saldo and saldo > 0 else None,
                currency=card.currency or None,
                remind_offsets=(-7, -3, -1),
            )
            for due in next_occurrences({"monthly": {"day": card.due_day}}, on_date, count=2)
        ]
