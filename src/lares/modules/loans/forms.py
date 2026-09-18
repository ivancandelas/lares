from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from lares.core.forms import LaresForm, ResourceForm
from lares.core.models import Link
from lares.core.models.resource import Resource

from .models import Loan, LoanPayment

SECURES = "secures"


class LoanForm(ResourceForm):
    """El préstamo puede colgar de una cosa: la hipoteca, de la casa.

    Sin esa arista, el inmueble aparece en el patrimonio por su valor entero y
    la deuda que lo grava vive en otra pantalla. Juntos dicen lo que de verdad
    es tuyo.
    """

    secured_by = forms.ModelChoiceField(
        queryset=Resource.objects.none(), required=False, label="Garantizado por",
        help_text="La casa de una hipoteca, el coche de un crédito automotriz.",
    )

    GROUPS = (
        ("Qué préstamo es", ["name", "direction", "counterpart", "principal",
                             "is_informal", "secured_by"]),
        ("Intereses", ["interest_kind", "annual_rate"]),
        ("Cuándo y cuánto se paga", ["started_on", "term_months", "payment_amount",
                                     "payment_day"]),
        ("Estado", ["state", "status"]),
        ("Lo acordado", ["description"]),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["secured_by"].queryset = Resource._base_manager.filter(
                household=self.household, archived_at__isnull=True,
            ).exclude(kind__in=("loan", "policy", "service", "subscription"))
        if self.instance.pk:
            actual = secured_resource(self.instance)
            if actual:
                self.fields["secured_by"].initial = actual.pk

    @transaction.atomic
    def save(self, commit=True):
        loan = super().save(commit=commit)
        if not commit:
            return loan

        ctype_loan = ContentType.objects.get_for_model(Loan)
        elegido = self.cleaned_data.get("secured_by")
        Link.objects.filter(role=SECURES, source_type=ctype_loan,
                            source_id=loan.pk).delete()
        if elegido:
            concreto = elegido.as_concrete()
            Link.objects.create(
                household=self.household,
                source_type=ctype_loan, source_id=loan.pk, role=SECURES,
                target_type=ContentType.objects.get_for_model(concreto.__class__),
                target_id=concreto.pk,
            )
        return loan

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


def secured_resource(loan):
    """La cosa que garantiza este préstamo, si hay alguna."""
    enlace = Link.objects.filter(
        role=SECURES,
        source_type=ContentType.objects.get_for_model(Loan), source_id=loan.pk,
    ).first()
    return enlace.target if enlace else None


def loans_against(resource) -> list:
    """Los préstamos que gravan esta cosa."""
    concreto = resource.as_concrete()
    ids = Link.objects.filter(
        role=SECURES,
        target_type=ContentType.objects.get_for_model(concreto.__class__),
        target_id=concreto.pk,
    ).values_list("source_id", flat=True)
    return [x for x in Loan.objects.filter(pk__in=ids) if not x.is_settled]
