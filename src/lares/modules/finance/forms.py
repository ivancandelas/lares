import datetime as dt

from django import forms
from django.db import transaction

from lares.core.forms import LaresForm, ResourceForm
from lares.core.models import Account

from .models import CreditCard
from .models_budget import Budget
from .models_installment import InstallmentPlan
from .models_provision import Provision


class CreditCardForm(ResourceForm):
    GROUPS = (
        ("Qué tarjeta es", ["name", "issuer", "last_four", "owner"]),
        ("Fechas y límite", ["credit_limit", "cut_day", "due_day", "apr"]),
        ("Dónde viven sus movimientos", ["account", "currency", "status"]),
    )

    class Meta:
        model = CreditCard
        fields = ["name", "issuer", "account", "last_four", "credit_limit",
                  "cut_day", "due_day", "apr", "owner", "currency", "status"]
        labels = {
            "name": "Cómo la llamas",
            "issuer": "Banco",
            "account": "Cuenta donde viven sus movimientos",
            "last_four": "Últimos 4 dígitos",
            "credit_limit": "Límite",
            "cut_day": "Día de corte",
            "due_day": "Día límite de pago",
            "apr": "Tasa anual (%)",
            "owner": "Titular",
            "currency": "Moneda",
            "status": "Estado",
        }
        help_texts = {
            "last_four": "Nunca guardes el número completo.",
            "due_day": "De aquí sale el aviso de pago cada mes.",
        }


class ProvisionForm(LaresForm):
    """Apartar no es mover dinero: es decir que ya tiene dueño."""

    GROUPS = (
        ("Para qué", ["name", "target_amount", "due_on"]),
        ("Dónde está y cuánto llevas", ["account", "saved_amount", "is_active"]),
        ("Nota", ["note"]),
    )

    class Meta:
        model = Provision
        fields = ["name", "target_amount", "due_on", "account", "saved_amount",
                  "is_active", "note"]
        labels = {
            "name": "Para qué",
            "target_amount": "Cuánto hace falta",
            "due_on": "Para cuándo",
            "account": "En qué cuenta está",
            "saved_amount": "Cuánto llevas apartado",
            "is_active": "Activa",
            "note": "Nota",
        }
        help_texts = {
            "target_amount": "Lo que costará cuando llegue.",
            "due_on": "Con esto te digo cuánto apartar cada mes.",
            "saved_amount": "No mueve dinero: solo deja de contarlo como disponible.",
        }


class BudgetForm(LaresForm):
    class Meta:
        model = Budget
        fields = ["account", "amount", "is_active", "note"]
        labels = {
            "account": "En qué",
            "amount": "Cuánto al mes",
            "is_active": "Activo",
            "note": "Nota",
        }
        help_texts = {
            "account": "Una categoría de gasto: supermercado, gasolina, mascotas.",
            "amount": "Te aviso cuando gastes más rápido que el mes, no el día 31.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["account"].queryset = Account._base_manager.filter(
                household=self.household, type=Account.Type.EXPENSE, is_active=True
            )


class InstallmentPlanForm(LaresForm):
    """Registrar una compra a meses.

    El asiento se hace por el total: la deuda existe desde el primer dia. Lo
    que el modelo anade es saber que parte de ese saldo todavia no te exigen.
    """

    GROUPS = (
        ("Qué compraste", ["description", "merchant", "card", "category"]),
        ("Cómo quedó", ["total_amount", "months", "first_charge_on",
                        "interest_free", "installment_amount"]),
    )

    category = forms.ModelChoiceField(
        queryset=Account.objects.none(), label="Categoría del gasto",
        help_text="En qué se contabiliza: electrónica, muebles, viajes.",
    )

    class Meta:
        model = InstallmentPlan
        fields = ["description", "merchant", "card", "total_amount", "months",
                  "first_charge_on", "interest_free", "installment_amount"]
        labels = {
            "description": "Qué compraste",
            "merchant": "Dónde",
            "card": "Con qué tarjeta",
            "total_amount": "Total de la compra",
            "months": "En cuántos meses",
            "first_charge_on": "Primer cargo",
            "interest_free": "Sin intereses",
            "installment_amount": "Mensualidad que te cobran",
        }
        help_texts = {
            "total_amount": "El precio completo, no la mensualidad.",
            "months": "Los meses sin intereses que te dieron.",
            "first_charge_on": "El corte en el que aparece el primer cargo.",
            "installment_amount": "Solo si hay intereses. Déjalo vacío en meses "
                                  "sin intereses y lo calculo yo.",
        }

    def clean(self):
        datos = super().clean()
        if not datos.get("interest_free") and not datos.get("installment_amount"):
            self.add_error(
                "installment_amount",
                "Con intereses hace falta la mensualidad: no es el total entre "
                "los meses.",
            )
        return datos

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["category"].queryset = Account._base_manager.filter(
                household=self.household, type=Account.Type.EXPENSE, is_active=True
            )
        self.fields["first_charge_on"].initial = dt.date.today()

    @transaction.atomic
    def save(self, commit=True):
        plan = super().save(commit=False)
        plan.household = self.household
        if not commit:
            return plan

        from lares.core.models import Entry, Posting

        asiento = Entry.objects.create(
            household=self.household, date=plan.first_charge_on,
            description=f"{plan.description} ({plan.months} meses)",
            source="installments", counterparty=plan.merchant,
        )
        # El total, no la mensualidad: es deuda desde el primer dia.
        Posting.objects.create(household=self.household, entry=asiento,
                               account=self.cleaned_data["category"],
                               amount=plan.total_amount)
        Posting.objects.create(household=self.household, entry=asiento,
                               account=plan.card.account,
                               amount=-plan.total_amount)
        plan.entry = asiento
        plan.save()
        return plan
