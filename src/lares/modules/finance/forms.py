from lares.core.forms import LaresForm, ResourceForm
from lares.core.models import Account

from .models import CreditCard
from .models_budget import Budget
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
