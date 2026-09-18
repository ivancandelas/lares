from django.contrib.contenttypes.models import ContentType

from lares.core.models import Link
from lares.core.registry import Check, Finding

from .models import CreditCard


class CardWithoutStatement(Check):
    key = "finance.card_no_statement"
    label = "Tarjeta sin estado de cuenta"
    severity = "normal"

    def run(self, household):
        ctype = ContentType.objects.get_for_model(CreditCard)
        con_docs = set(
            Link.objects.filter(role="documents", target_type=ctype)
            .values_list("target_id", flat=True)
        )
        return [
            Finding(
                check=self.key,
                title=f"{card} no tiene ningún estado de cuenta",
                detail="Sin estados de cuenta no se puede conciliar ni saber a dónde va el dinero.",
                severity=self.severity,
                subject_type="credit_card",
                subject_id=card.pk,
            )
            for card in CreditCard.objects.filter(status=CreditCard.Status.ACTIVE)
            if card.pk not in con_docs
        ]


class CardOverLimit(Check):
    key = "finance.card_over_limit"
    label = "Tarjeta cerca del límite"
    severity = "high"

    UMBRAL = 0.9

    def run(self, household):
        hallazgos = []
        for card in CreditCard.objects.filter(status=CreditCard.Status.ACTIVE):
            if not card.credit_limit or not card.account:
                continue
            usado = card.account.balance / card.credit_limit
            if usado >= self.UMBRAL:
                hallazgos.append(Finding(
                    check=self.key,
                    title=f"{card} está al {usado:.0%} de su límite",
                    detail="Pasar del límite genera comisión y afecta al historial crediticio.",
                    severity=self.severity,
                    subject_type="credit_card",
                    subject_id=card.pk,
                ))
        return hallazgos
