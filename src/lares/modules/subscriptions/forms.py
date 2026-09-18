from django import forms

from lares.core.forms import ResourceForm

from .models import Subscription


class SubscriptionForm(ResourceForm):
    # Sin esto, una dirección escrita sin protocolo acaba en http.
    cancel_url = forms.URLField(
        required=False, assume_scheme="https", label="Cómo se cancela",
        help_text="El enlace exacto. Dentro de un año no lo vas a encontrar.",
    )

    GROUPS = (
        ("Qué es", ["name", "service_kind", "provider", "plan", "started_on"]),
        ("Cuánto y cada cuánto", ["amount", "cycle", "charge_day", "paid_with",
                                  "currency"]),
        ("De quién es la cuenta", ["access", "account_holder", "owner"]),
        ("Permanencia y baja", ["commitment_until", "cancel_url", "status"]),
        ("Si cambió de precio", ["previous_amount", "price_changed_on"]),
        ("Notas", ["description"]),
    )

    class Meta:
        model = Subscription
        fields = ["name", "service_kind", "provider", "plan", "started_on",
                  "amount", "cycle", "charge_day", "paid_with", "currency",
                  "access", "account_holder", "owner",
                  "commitment_until", "cancel_url", "status",
                  "previous_amount", "price_changed_on", "description"]
        labels = {
            "name": "Qué es",
            "service_kind": "Tipo",
            "provider": "A quién se lo pagas",
            "plan": "Plan",
            "started_on": "Desde cuándo",
            "amount": "Importe del cargo",
            "cycle": "Cada cuánto",
            "charge_day": "Día del cargo",
            "paid_with": "Con qué se paga",
            "currency": "Moneda",
            "access": "De quién es la cuenta",
            "account_holder": "A nombre de quién está",
            "owner": "Quién la usa",
            "commitment_until": "Permanencia hasta",
            "cancel_url": "Cómo se cancela",
            "status": "Estado",
            "previous_amount": "Cuánto costaba antes",
            "price_changed_on": "Cambió de precio el",
            "description": "Notas",
        }
        help_texts = {
            "amount": "Se convierte en coste anual para poder compararlas.",
            "paid_with": "Si cambias de tarjeta, sabrás cuáles se van a caer.",
            "access": "«Es de otra persona» cuando tú solo pagas, como la cuenta de un hijo.",
            "commitment_until": "El único momento con poder de negociación.",
            "cancel_url": "El enlace exacto. Dentro de un año no lo vas a encontrar.",
            "previous_amount": "Si lo rellenas, te aviso de cuánto subió al año.",
        }
