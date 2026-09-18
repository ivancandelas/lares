"""Lo que se paga de mas sin que nadie lo note."""

import datetime as dt

from lares.core.registry import Check, Finding

from .models import Subscription

REVISION_MESES = 12


class WithoutPaymentMethod(Check):
    key = "subscriptions.no_payment"
    label = "Suscripción sin saber con qué se paga"
    severity = "normal"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"No sabes con qué tarjeta pagas {s.name}",
                detail="Si cambias de tarjeta, esta se cae sin avisar.",
                severity=self.severity,
                subject_type="subscription", subject_id=s.pk,
            )
            for s in Subscription.objects.filter(status=Subscription.Status.ACTIVE,
                                                 paid_with__isnull=True)
        ]


class PriceRose(Check):
    key = "subscriptions.price_rose"
    label = "Subió de precio"
    severity = "normal"

    def run(self, household):
        hallazgos = []
        for s in Subscription.objects.filter(status=Subscription.Status.ACTIVE):
            subida = s.price_rise
            if not subida:
                continue
            cuando = f" en {s.price_changed_on:%B}" if s.price_changed_on else ""
            detalle = (f"De {s.previous_amount:,.0f} a {s.amount:,.0f}{cuando}. "
                       f"Son {subida * 12:,.0f} más al año.")
            if not s.is_mine_to_cancel:
                detalle += " La cuenta no es tuya, pero el cargo sí."
            hallazgos.append(Finding(
                check=self.key, title=f"{s.name} subió de precio",
                detail=detalle, severity=self.severity,
                subject_type="subscription", subject_id=s.pk,
            ))
        return hallazgos


class WorthReviewing(Check):
    """«¿Sigues usando esto?»

    Lo que no se revisa nunca se paga para siempre.
    """

    key = "subscriptions.review"
    label = "Suscripción sin revisar hace tiempo"
    severity = "low"

    def run(self, household):
        limite = dt.date.today() - dt.timedelta(days=REVISION_MESES * 30)
        pendientes = [
            s for s in Subscription.objects.filter(status=Subscription.Status.ACTIVE)
            if (s.verified_on or s.created_at.date()) < limite
        ]
        if not pendientes:
            return []
        anual = sum(s.yearly_cost or 0 for s in pendientes)
        return [Finding(
            check=self.key,
            title=f"{len(pendientes)} suscripción(es) sin revisar en un año",
            detail=(f"Suman {anual:,.0f} al año: "
                    + ", ".join(s.name for s in pendientes[:5])),
            severity=self.severity,
        )]
