"""Lo que se olvida de un prestamo."""

from lares.core.registry import Check, Finding

from .models import Loan

SILENCIO_MESES = 4


class ForgottenLoan(Check):
    """El que diste y nadie ha pagado en meses.

    Es el hueco caracteristico de este modulo: cuando debes, llega un recibo
    cada mes; cuando te deben, no llega nada y el prestamo se evapora.
    """

    key = "loans.forgotten"
    label = "Préstamo que nadie está pagando"
    severity = "high"

    def run(self, household):
        hallazgos = []
        for loan in Loan.objects.filter(status=Loan.Status.ACTIVE,
                                        direction=Loan.Direction.LENT):
            silencio = loan.months_silent
            if loan.is_settled or silencio is None or silencio < SILENCIO_MESES:
                continue
            quien = f" {loan.counterpart}" if loan.counterpart else ""
            hallazgos.append(Finding(
                check=self.key,
                title=f"Llevas {silencio} meses sin cobrar de {loan.name}",
                detail=(f"Quedan {loan.outstanding:,.0f} por cobrar{quien}. "
                        "Cuando te deben no llega ningún recibo que te lo recuerde."),
                severity=self.severity,
                subject_type="loan", subject_id=loan.pk,
            ))
        return hallazgos


class InformalWithoutRecord(Check):
    """Un préstamo de palabra sin nada escrito acaba en «yo recordaba otra cosa»."""

    key = "loans.no_record"
    label = "Préstamo sin nada por escrito"
    severity = "normal"

    UMBRAL = 5000

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{loan.name} no tiene nada por escrito",
                detail=(f"Son {loan.principal:,.0f}. Basta una nota con la fecha, "
                        "el importe y lo acordado."),
                severity=self.severity,
                subject_type="loan", subject_id=loan.pk,
            )
            for loan in Loan.objects.filter(status=Loan.Status.ACTIVE,
                                            is_informal=True)
            if loan.principal >= self.UMBRAL and not loan.description
        ]


class Overpaid(Check):
    """Si lo abonado supera el capital, algo se registró mal."""

    key = "loans.overpaid"
    label = "Abonos por encima del capital"
    severity = "normal"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{loan.name} tiene más abonado que su importe",
                detail=(f"Capital {loan.principal:,.0f}, abonado "
                        f"{loan.paid:,.0f}. Revisa si algún abono llevaba intereses."),
                severity=self.severity,
                subject_type="loan", subject_id=loan.pk,
            )
            for loan in Loan.objects.filter(status=Loan.Status.ACTIVE)
            if loan.paid > loan.principal
        ]
