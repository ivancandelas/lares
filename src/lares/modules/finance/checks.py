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


class CannotPayInFull(Check):
    """El saldo al corte no cabe en lo que tienes disponible.

    Es el momento en que una tarjeta pasa de ser un medio de pago a ser un
    credito caro, y conviene verlo antes de la fecha limite, no despues.
    """

    key = "finance.cannot_pay_full"
    label = "El pago sin intereses no cabe en lo disponible"
    severity = "high"

    def run(self, household):
        from .services import available

        disponible = available(household)["available"]
        hallazgos = []
        for card in CreditCard.objects.filter(status=CreditCard.Status.ACTIVE):
            pngi = card.no_interest_payment
            if not pngi or pngi <= 0 or pngi <= disponible:
                continue
            falta = pngi - disponible
            hallazgos.append(Finding(
                check=self.key,
                title=f"No te alcanza para liquidar {card}",
                detail=(f"Al corte debes {pngi:,.0f} y tienes {disponible:,.0f} "
                        f"disponibles: faltan {falta:,.0f}. Pagar de menos genera "
                        "intereses sobre todo el periodo, no sobre la diferencia."),
                severity=self.severity,
                subject_type="credit_card", subject_id=card.pk,
            ))
        return hallazgos


class BudgetPace(Check):
    """Gastar mas rapido que el mes.

    Avisar el dia 31 de que te pasaste no cambia nada. Avisar el 12 de que a
    este ritmo te vas a pasar, si.
    """

    key = "finance.budget_pace"
    label = "Vas más rápido que el mes"
    severity = "normal"

    def run(self, household):
        from .services import budgets

        datos = budgets(household)
        hallazgos = []
        for linea in datos["over"]:
            hallazgos.append(Finding(
                check=self.key,
                title=f"Te pasaste del tope de {linea.budget.account.name}",
                detail=(f"Llevas {linea.spent:,.0f} de {linea.planned:,.0f} "
                        f"y aún queda mes."),
                severity="high",
            ))
        for linea in datos["ahead"]:
            hallazgos.append(Finding(
                check=self.key,
                title=f"{linea.budget.account.name} va rápido este mes",
                detail=(f"Llevas {linea.used:.0%} del tope con {linea.month_elapsed:.0%} "
                        f"del mes. A este ritmo acabarías en {linea.projected:,.0f}."),
                severity=self.severity,
            ))
        return hallazgos
