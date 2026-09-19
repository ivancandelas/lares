from django import forms
from django.contrib.contenttypes.models import ContentType

from lares.core.forms import LaresForm
from lares.core.models.resource import Resource

from .models import MaintenancePlan, WorkOrder


class SubjectMixin:
    """Elegir «a qué cosa» sin que el usuario vea el grafo por debajo."""

    subject = forms.ModelChoiceField(
        queryset=Resource.objects.none(), label="De qué cosa",
        help_text="El coche, la casa, el boiler.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["subject"].queryset = Resource._base_manager.filter(
                household=self.household, archived_at__isnull=True,
            ).exclude(kind__in=("policy", "service"))
        if not self.is_new and self.instance.subject_id:
            self.fields["subject"].initial = self.instance.subject_id

    def save(self, commit=True):
        obj = super().save(commit=False)
        elegido = self.cleaned_data["subject"].as_concrete()
        obj.subject_type = ContentType.objects.get_for_model(elegido.__class__)
        obj.subject_id = elegido.pk
        if self.household and not obj.household_id:
            obj.household = self.household
        if commit:
            obj.save()
        return obj


class MaintenancePlanForm(SubjectMixin, LaresForm):
    subject = SubjectMixin.subject

    GROUPS = (
        ("Qué y de qué", ["title", "subject"]),
        ("Cada cuánto", ["basis", "every_months", "every_km", "last_done_on"]),
        ("Quién y cuánto", ["preferred_provider", "estimated_cost", "is_active"]),
    )

    class Meta:
        model = MaintenancePlan
        fields = ["title", "basis", "every_months", "every_km", "last_done_on",
                  "estimated_cost", "preferred_provider", "is_active"]
        labels = {
            "title": "Qué hay que hacer",
            "basis": "Cada qué",
            "every_months": "Cada cuántos meses",
            "every_km": "Cada cuántos km",
            "last_done_on": "La última vez fue",
            "estimated_cost": "Cuánto suele costar",
            "preferred_provider": "Quién suele hacerlo",
            "is_active": "Activo",
        }
        help_texts = {
            "every_km": "Solo para coches. El aviso lo calcula el propio módulo.",
            "last_done_on": "De aquí sale la próxima fecha.",
        }


class WorkOrderForm(SubjectMixin, LaresForm):
    subject = SubjectMixin.subject

    GROUPS = (
        ("Qué se hizo", ["title", "subject", "done_on", "plan"]),
        ("Quién y cuánto", ["provider", "cost", "currency", "odometer_km"]),
        ("Garantía y notas", ["warranty_until", "notes"]),
    )

    class Meta:
        model = WorkOrder
        fields = ["title", "done_on", "provider", "cost", "currency",
                  "odometer_km", "warranty_until", "plan", "notes"]
        labels = {
            "title": "Qué se hizo",
            "done_on": "Cuándo",
            "provider": "Quién lo hizo",
            "cost": "Cuánto costó",
            "currency": "Moneda",
            "odometer_km": "Kilometraje",
            "warranty_until": "Garantía del trabajo hasta",
            "plan": "Corresponde al plan",
            "notes": "Notas",
        }
        help_texts = {
            "provider": "Si vuelve a fallar, sabrás a quién llamar.",
            "warranty_until": "La del trabajo, no la del objeto.",
        }

    def save(self, commit=True):
        orden = super().save(commit=commit)
        # Registrar el trabajo adelanta el plan: si no, el aviso seguiría ahí.
        if commit and orden.plan_id:
            plan = orden.plan
            if not plan.last_done_on or plan.last_done_on < orden.done_on:
                plan.last_done_on = orden.done_on
                plan.save(update_fields=["last_done_on", "updated_at"])
        return orden
