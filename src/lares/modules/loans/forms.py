from django import forms

from lares.core.forms import LaresForm, ResourceForm

from .models import Loan, LoanPayment


class LoanForm(ResourceForm):
    GROUPS = (
        ("Qué préstamo es", ["name", "direction", "counterpart", "principal",
                             "is_informal"]),
        ("Intereses", ["interest_kind", "annual_rate"]),
        ("Cuándo y cuánto se paga", ["started_on", "term_months", "payment_amount",
                                     "payment_day"]),
        ("Estado", ["state", "status"]),
        ("Lo acordado", ["description"]),
    )

    class Meta:
        model = Loan
        fields = ["name", "direction", "counterpart", "principal", "is_informal",
                  "interest_kind", "annual_rate", "started_on", "term_months",
                  "payment_amount", "payment_day", "state", "status",
                  "currency", "description"]
        labels = {
            "name": "Cómo lo llamas",
            "direction": "Sentido",
            "counterpart": "Con quién",
            "principal": "Importe original",
            "is_informal": "Sin contrato, de palabra",
            "interest_kind": "Intereses",
            "annual_rate": "Tasa anual (%)",
            "started_on": "Desde cuándo",
            "term_months": "Plazo en meses",
            "payment_amount": "Cuota",
            "payment_day": "Día de pago",
            "state": "Estado del préstamo",
            "status": "Registro",
            "currency": "Moneda",
            "description": "Lo acordado",
        }
        help_texts = {
            "direction": "«Lo presté» son los que se olvidan: no llega ningún recibo.",
            "principal": "Lo prestado, sin intereses.",
            "payment_day": "Con esto el cobro o el pago aparece solo cada mes.",
            "description": "Aunque sea de palabra, escribe aquí lo que acordaron.",
        }


class LoanPaymentForm(LaresForm):
    """Registrar un abono. Separar capital de intereses es lo que baja el saldo."""

    class Meta:
        model = LoanPayment
        fields = ["date", "amount", "principal_part", "interest_part", "note"]
        labels = {
            "date": "Cuándo",
            "amount": "Cuánto",
            "principal_part": "A capital",
            "interest_part": "A intereses",
            "note": "Nota",
        }
        help_texts = {
            "principal_part": "Si lo dejas vacío, todo cuenta como capital.",
        }

    def __init__(self, *args, loan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.loan = loan
        self.fields["date"].initial = forms.DateField().to_python(None)
        if loan and loan.payment_amount:
            self.fields["amount"].initial = loan.payment_amount

    def save(self, commit=True):
        abono = super().save(commit=False)
        if self.loan:
            abono.loan = self.loan
            abono.household = self.loan.household
        if commit:
            abono.save()
            # Un abono al día saca al préstamo del estado de atraso.
            if self.loan and self.loan.state == Loan.State.LATE:
                self.loan.state = Loan.State.CURRENT
                self.loan.save(update_fields=["state", "updated_at"])
            if self.loan and self.loan.is_settled:
                self.loan.state = Loan.State.PAID
                self.loan.save(update_fields=["state", "updated_at"])
        return abono
