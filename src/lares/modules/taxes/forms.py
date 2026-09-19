from django import forms

from lares.core.forms import LaresForm
from lares.core.models import Document, Party

from .models import Deduction, Filing, TaxProfile, Withholding


class TaxProfileForm(LaresForm):
    GROUPS = (
        ("Quién declara", ["taxpayer", "rfc", "regime"]),
        ("Datos del ejercicio", ["started_on", "uma_annual"]),
        ("Notas", ["note", "is_active"]),
    )

    class Meta:
        model = TaxProfile
        fields = ["taxpayer", "rfc", "regime", "started_on", "uma_annual",
                  "note", "is_active"]
        labels = {
            "taxpayer": "Quién declara", "rfc": "RFC", "regime": "Régimen",
            "started_on": "Desde cuándo", "uma_annual": "UMA anual",
            "note": "Nota", "is_active": "Activo",
        }
        help_texts = {
            "regime": "De él salen las fechas: quien declara cada mes no tiene "
                      "el mismo calendario que un asalariado.",
            "uma_annual": "El SAT la publica cada febrero. Sin ella no se "
                          "aplica el tope de cinco UMA a tus deducciones.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["taxpayer"].queryset = Party._base_manager.filter(
                household=self.household, kind=Party.Kind.PERSON)


class DeductionForm(LaresForm):
    GROUPS = (
        ("Qué se deduce", ["profile", "kind", "amount", "date"]),
        ("De dónde sale", ["document", "entry", "description", "beneficiary"]),
        ("Notas", ["note"]),
    )

    class Meta:
        model = Deduction
        fields = ["profile", "kind", "amount", "date", "document", "entry",
                  "description", "beneficiary", "note"]
        labels = {
            "profile": "De quién", "kind": "De qué tipo", "amount": "Importe",
            "date": "Fecha", "document": "Con qué factura",
            "entry": "Qué movimiento", "description": "Concepto",
            "beneficiary": "A nombre de quién", "note": "Nota",
        }
        help_texts = {
            "document": "Sin CFDI casi nada es deducible: es lo primero que "
                        "pide el SAT.",
            "beneficiary": "Cónyuge, hijos o padres también cuentan en varias "
                           "deducciones personales.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["profile"].queryset = TaxProfile._base_manager.filter(
                household=self.household, is_active=True)
            self.fields["document"].queryset = Document._base_manager.filter(
                household=self.household, archived_at__isnull=True)
            self.fields["beneficiary"].queryset = Party._base_manager.filter(
                household=self.household)

    def clean(self):
        datos = super().clean()
        documento, perfil = datos.get("document"), datos.get("profile")
        if documento and perfil:
            ya = Deduction.objects.filter(profile=perfil, document=documento)
            if not self.is_new:
                ya = ya.exclude(pk=self.instance.pk)
            if ya.exists():
                self.add_error("document",
                               "Esa factura ya está deducida. Deducirla dos "
                               "veces infla la declaración sin que se note.")
        return datos


class WithholdingForm(LaresForm):
    class Meta:
        model = Withholding
        fields = ["profile", "kind", "amount", "date", "payer", "document",
                  "note"]
        labels = {
            "profile": "De quién", "kind": "Qué impuesto", "amount": "Importe",
            "date": "Fecha", "payer": "Quién retuvo",
            "document": "Comprobante", "note": "Nota",
        }
        help_texts = {
            "amount": "Lo que ya se enteró por ti. Si no se declara, se paga "
                      "dos veces.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["profile"].queryset = TaxProfile._base_manager.filter(
                household=self.household, is_active=True)
            self.fields["payer"].queryset = Party._base_manager.filter(
                household=self.household)
            self.fields["document"].queryset = Document._base_manager.filter(
                household=self.household, archived_at__isnull=True)


class FilingForm(LaresForm):
    class Meta:
        model = Filing
        fields = ["profile", "kind", "period", "filed_on", "amount_paid",
                  "balance_favor", "receipt", "note"]
        labels = {
            "profile": "De quién", "kind": "Qué declaración",
            "period": "Periodo", "filed_on": "Presentada el",
            "amount_paid": "Lo que pagaste", "balance_favor": "Saldo a favor",
            "receipt": "Acuse", "note": "Nota",
        }
        help_texts = {
            "period": "AAAA-MM para un pago provisional, AAAA para la anual.",
            "receipt": "Es lo único que prueba que presentaste.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            self.fields["profile"].queryset = TaxProfile._base_manager.filter(
                household=self.household, is_active=True)
            self.fields["receipt"].queryset = Document._base_manager.filter(
                household=self.household, archived_at__isnull=True)

    def clean_period(self):
        periodo = (self.cleaned_data.get("period") or "").strip()
        import re

        if not re.fullmatch(r"\d{4}(-\d{2})?", periodo):
            raise forms.ValidationError("Usa AAAA-MM o AAAA.")
        return periodo
