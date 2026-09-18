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

        # El importe correcto es el saldo AL CORTE, no el de hoy: el de hoy
        # incluye compras que todavia no vencen, y pagar de menos genera
        # intereses sobre todo el periodo.
        pngi = card.no_interest_payment if card.cut_day else None
        if pngi is None and card.account:
            pngi = card.account.balance

        return [
            ObligationSpec(
                dedupe_key=f"card:{card.pk}:payment:{due:%Y-%m}",
                title=f"Pago de {card}",
                due_on=due,
                severity="high",
                amount=pngi if pngi and pngi > 0 else None,
                currency=card.currency or None,
                counterparty=card.issuer,
                remind_offsets=(-7, -3, -1),
                payload={"kind": "no_interest"},
            )
            for due in next_occurrences({"monthly": {"day": card.due_day}}, on_date, count=2)
        ]
