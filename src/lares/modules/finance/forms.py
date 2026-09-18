from lares.core.forms import ResourceForm

from .models import CreditCard


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
