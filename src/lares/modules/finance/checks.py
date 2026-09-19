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


class InstallmentsCommitted(Check):
    """Lo que ya esta comprometido en mensualidades.

    Una compra a meses no duele el dia que se hace: duele los once meses
    siguientes, cuando ya nadie se acuerda de por que.
    """

    key = "finance.installments"
    label = "Comprometido en compras a meses"
    severity = "low"

    def run(self, household):
        import datetime as dt

        hallazgos = []
        for card in CreditCard.objects.filter(status=CreditCard.Status.ACTIVE):
            planes = [p for p in card.installment_plans.filter(is_active=True)
                      if not p.is_finished]
            if not planes:
                continue
            mensual = sum(p.installment for p in planes)
            hasta = max(p.ends_on for p in planes)
            meses = max(
                (hasta.year - dt.date.today().year) * 12
                + (hasta.month - dt.date.today().month), 0
            )
            hallazgos.append(Finding(
                check=self.key,
                title=f"{mensual:,.0f} al mes comprometidos en {card}",
                detail=(f"{len(planes)} compra(s) a meses, hasta "
                        f"{hasta:%m/%Y}: {meses} meses más."),
                severity=self.severity,
                subject_type="credit_card", subject_id=card.pk,
            ))
        return hallazgos


class InstallmentInterest(Check):
    """Lo que cuesta pagar a plazos.

    Los meses sin intereses son gratis; los que llevan intereses no, y la
    diferencia casi nunca se ve en el momento de comprar porque el banco solo
    ensena la mensualidad.
    """

    key = "finance.installment_interest"
    label = "Intereses en una compra a meses"
    severity = "normal"

    def run(self, household):
        from .models_installment import InstallmentPlan

        hallazgos = []
        for plan in InstallmentPlan.objects.filter(is_active=True):
            if plan.is_finished or plan.interest_total <= 0:
                continue
            hallazgos.append(Finding(
                check=self.key,
                title=f"{plan.description} te cuesta "
                      f"{plan.interest_total:,.0f} de intereses",
                detail=(f"Precio {plan.total_amount:,.0f} y acabarás pagando "
                        f"{plan.total_to_pay:,.0f}: un "
                        f"{plan.interest_share:.0%} más."),
                severity=self.severity,
                subject_type="credit_card", subject_id=plan.card_id,
            ))
        return hallazgos


class PlanDrifting(Check):
    """Una categoría que, al ritmo que va, cierra el año pasada.

    Lo que se mira es la proyeccion de cierre y no el gasto del mes: un mes
    malo no dice nada y avisar por cada uno acaba con que nadie mire la
    pantalla. Tres meses seguidos por encima si cambian el cierre, y eso es
    justo lo que la proyeccion recoge.
    """

    key = "finance.plan_drift"
    label = "Presupuesto que se va a pasar"
    severity = "normal"

    # Antes de esto no hay periodo suficiente para proyectar nada serio.
    MINIMO = 0.15

    def run(self, household):
        from .models_plan import Plan
        from .services_plan import report as plan_report

        hallazgos = []
        for plan in Plan.objects.filter(is_active=True):
            if plan.elapsed < self.MINIMO:
                continue
            informe = plan_report(household, plan)
            for linea in informe.lines:
                if not linea.is_drifting:
                    continue
                hallazgos.append(Finding(
                    check=self.key,
                    title=f"{linea.account.name} va a cerrar "
                          f"{linea.projected_variance:,.0f} por encima",
                    detail=(f"Llevas {linea.actual:,.0f} de "
                            f"{linea.planned:,.0f} con el "
                            f"{plan.elapsed:.0%} del periodo corrido "
                            f"({plan.name})."),
                    severity=self.severity,
                    subject_type="plan", subject_id=plan.pk,
                ))
        return hallazgos


class PlanUnplanned(Check):
    """Gasto real en categorías que nadie presupuestó.

    Es donde se escapa el dinero de quien presupuesta solo lo que ya sabe que
    va a gastar: el presupuesto cuadra y la cuenta no.
    """

    key = "finance.plan_unplanned"
    label = "Gasto fuera del presupuesto"
    severity = "low"

    def run(self, household):
        from .models_plan import Plan
        from .services_plan import report as plan_report

        hallazgos = []
        for plan in Plan.objects.filter(is_active=True,
                                        kind=Plan.Kind.ANNUAL):
            informe = plan_report(household, plan)
            if not informe.unplanned or not informe.lines:
                continue
            total = sum(x.actual for x in informe.unplanned)
            hallazgos.append(Finding(
                check=self.key,
                title=f"{total:,.0f} gastados fuera del presupuesto "
                      f"de {plan.name}",
                detail=(f"En {len(informe.unplanned)} categorías que nadie "
                        f"previó. La mayor es "
                        f"{informe.unplanned[0].account.name}."),
                severity=self.severity,
                subject_type="plan", subject_id=plan.pk,
            ))
        return hallazgos


class NegativeCash(Check):
    """Una cuenta de activo en negativo.

    El caso clasico es el efectivo. No se puede gastar dinero que nunca
    entro, asi que un saldo negativo significa siempre lo mismo: falta
    registrar de donde salio. Casi siempre es un retiro del cajero anotado
    como gasto en vez de como traspaso, y entonces el dinero se cuenta dos
    veces -una al sacarlo y otra al gastarlo-.
    """

    key = "finance.negative_asset"
    label = "Cuenta en negativo"
    severity = "normal"

    def run(self, household):
        from lares.core.models import Account

        return [
            Finding(
                check=self.key,
                title=f"{cuenta.name} tiene saldo negativo",
                detail=("No se puede gastar de una cuenta lo que nunca entró. "
                        "Suele ser un retiro anotado como gasto: si sacas del "
                        "banco para tener efectivo, es un traspaso entre dos "
                        "cuentas tuyas."),
                severity=self.severity,
            )
            for cuenta in Account.objects.filter(type=Account.Type.ASSET,
                                                 is_active=True)
            if cuenta.balance < 0
        ]
