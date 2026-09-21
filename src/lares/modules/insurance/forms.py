from django import forms
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from lares.core.forms import ResourceForm
from lares.core.models import Link
from lares.core.models.resource import Resource

from .models import Policy


class PolicyForm(ResourceForm):
    """Una póliza se define por lo que cubre.

    Por eso "qué asegura" está en el alta y no escondido en otra pantalla: una
    póliza que no se sabe a qué se refiere no sirve para reclamar.
    """

    covers = forms.ModelMultipleChoiceField(
        queryset=Resource.objects.none(), required=False, label="Qué asegura",
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="El coche, la casa, la guitarra. Puedes elegir varios.",
    )

    # Sin la vigencia no hay aviso de renovación, que es la razón
    # por la que una póliza se registra aquí.
    ESENCIALES = ("name", "insurer", "covers", "ends_on")

    GROUPS = (
        ("Qué póliza es", ["name", "branch", "policy_number", "insurer", "agent"]),
        ("Qué cubre", ["covers", "coverage_amount", "deductible", "beneficiaries"]),
        ("Cuánto y cuándo", ["premium", "premium_cycle", "premium_day",
                             "starts_on", "ends_on", "currency", "status"]),
    )

    class Meta:
        model = Policy
        fields = ["name", "branch", "policy_number", "insurer", "agent",
                  "coverage_amount", "deductible", "premium", "premium_cycle",
                  "premium_day", "starts_on", "ends_on", "beneficiaries",
                  "currency", "status"]
        labels = {
            "name": "Cómo la llamas",
            "branch": "Ramo",
            "policy_number": "Número de póliza",
            "insurer": "Aseguradora",
            "agent": "Agente",
            "coverage_amount": "Suma asegurada",
            "deductible": "Deducible",
            "premium": "Prima",
            "premium_cycle": "Cómo se paga",
            "premium_day": "Día de pago",
            "starts_on": "Vigente desde",
            "ends_on": "Vence el",
            "beneficiaries": "Beneficiarios",
            "currency": "Moneda",
            "status": "Estado",
        }
        help_texts = {
            "ends_on": "Avisa con 45 días: comparar otras opciones lleva semanas.",
            "coverage_amount": "Si queda por debajo del valor registrado, te lo digo.",
            "premium_day": "Solo si la prima se paga fraccionada.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["covers"].queryset = Resource._base_manager.filter(
                household=self.household, archived_at__isnull=True,
            ).exclude(kind__in=("policy", "service"))
        if not self.is_new:
            self.fields["covers"].initial = self.instance.insured_resources()

    @transaction.atomic
    def save(self, commit=True):
        policy = super().save(commit=commit)
        if not commit:
            return policy

        ctype_policy = ContentType.objects.get_for_model(Policy)
        elegidos = list(self.cleaned_data.get("covers") or [])

        Link.objects.filter(role="insures", source_type=ctype_policy,
                            source_id=policy.pk).exclude(
            target_id__in=[r.pk for r in elegidos]
        ).delete()

        for recurso in elegidos:
            concreto = recurso.as_concrete()
            Link.objects.get_or_create(
                household=self.household,
                source_type=ctype_policy, source_id=policy.pk,
                role="insures",
                target_type=ContentType.objects.get_for_model(concreto.__class__),
                target_id=concreto.pk,
                valid_from=policy.starts_on,
                defaults={"valid_to": policy.ends_on},
            )
        return policy
