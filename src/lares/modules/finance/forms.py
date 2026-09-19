import datetime as dt

from django import forms
from django.db import transaction

from lares.core.forms import GroupedForm, LaresForm, ResourceForm
from lares.core.models import Account

from .models import CreditCard
from .models_income import RecurringIncome as RecurringIncomeModel
from .models_installment import InstallmentPlan
from .models_plan import Plan as PlanModel
from .models_plan import PlanLine as PlanLineModel
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


class PlanForm(LaresForm):
    GROUPS = (
        ("Qué presupuesto", ["name", "kind", "currency"]),
        ("Periodo", ["year", "starts_on", "ends_on"]),
        ("Notas", ["note", "is_active"]),
    )

    class Meta:
        model = PlanModel
        fields = ["name", "kind", "currency", "year", "starts_on", "ends_on",
                  "note", "is_active"]
        labels = {
            "name": "Cómo lo llamas", "kind": "De qué tipo",
            "currency": "Moneda", "year": "Ejercicio",
            "starts_on": "Desde", "ends_on": "Hasta", "note": "Nota",
            "is_active": "Activo",
        }
        help_texts = {
            "kind": "El del año responde «¿voy como pensaba?». El de un "
                    "proyecto —una obra, un viaje— es donde más se desvía.",
            "year": "Solo para el del año.",
            "starts_on": "Solo para un proyecto. De aquí sale la proyección.",
        }

    def clean(self):
        datos = super().clean()
        if datos.get("kind") == PlanModel.Kind.PROJECT:
            if not datos.get("starts_on"):
                self.add_error("starts_on", "Un proyecto necesita fecha de "
                                            "inicio: sin ella no hay proyección.")
        elif not datos.get("year"):
            self.add_error("year", "Di de qué año es.")
        return datos


class PlanLineForm(LaresForm):
    class Meta:
        model = PlanLineModel
        fields = ["account", "amount", "cadence", "note"]
        labels = {"account": "En qué", "amount": "Previsto",
                  "cadence": "Cada cuánto", "note": "Nota"}
        help_texts = {
            "cadence": "«Al mes» para lo que se gasta parejo —el súper, la "
                       "gasolina— y además avisa dentro del mes. «En todo el "
                       "periodo» para lo que cae de golpe: vacaciones, el "
                       "mantenimiento del coche.",
        }

    def __init__(self, *args, plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan
        # En un proyecto lo normal es una cifra de golpe; en el del año, algo
        # que se gasta cada mes. Acertar el valor por defecto evita el error
        # más caro de este formulario: una cifra anual tomada por mensual.
        if plan and not self.instance.pk:
            self.fields["cadence"].initial = (
                PlanLineModel.Cadence.TOTAL if plan.is_project
                else PlanLineModel.Cadence.MONTHLY)
        if self.household:
            self.fields["account"].queryset = Account._base_manager.filter(
                household=self.household, is_active=True,
                type__in=[Account.Type.EXPENSE, Account.Type.INCOME])

    def clean_account(self):
        cuenta = self.cleaned_data["account"]
        if self.plan:
            ya = PlanLineModel.objects.filter(plan=self.plan, account=cuenta)
            if self.instance.pk:
                ya = ya.exclude(pk=self.instance.pk)
            if ya.exists():
                raise forms.ValidationError("Esa categoría ya está en el "
                                            "presupuesto.")
        return cuenta

    def save(self, commit=True):
        linea = super().save(commit=False)
        linea.plan = self.plan
        linea.household = self.plan.household
        if commit:
            linea.save()
        return linea


class RecurringIncomeForm(LaresForm):
    GROUPS = (
        ("Qué ingreso", ["name", "payer", "amount", "currency"]),
        ("Cada cuánto", ["cycle", "pay_day", "started_on", "ends_on"]),
        ("Dónde entra", ["account", "category"]),
        ("Notas", ["note", "is_active"]),
    )

    class Meta:
        model = RecurringIncomeModel
        fields = ["name", "payer", "amount", "currency", "cycle", "pay_day",
                  "started_on", "ends_on", "account", "category", "note",
                  "is_active"]
        labels = {
            "name": "Qué es", "payer": "Quién te paga",
            "amount": "Cuánto te llega", "currency": "Moneda",
            "cycle": "Cada cuánto", "pay_day": "Día de pago",
            "started_on": "Desde cuándo", "ends_on": "Hasta cuándo",
            "account": "Dónde entra", "category": "Cómo se clasifica",
            "note": "Nota", "is_active": "Activo",
        }
        help_texts = {
            "amount": "Lo que de verdad te llega, no el bruto.",
            "cycle": "De aquí sale la proyección de «¿me alcanza?».",
            "pay_day": "Si lo sabes, se muestra cuándo cae el próximo.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            cuentas = Account._base_manager.filter(household=self.household,
                                                   is_active=True)
            self.fields["account"].queryset = cuentas.filter(
                type=Account.Type.ASSET)
            self.fields["category"].queryset = cuentas.filter(
                type=Account.Type.INCOME)
            from lares.core.models import Party
            self.fields["payer"].queryset = Party._base_manager.filter(
                household=self.household, archived_at__isnull=True)


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


class MonthlyAmountsForm(GroupedForm, forms.Form):
    """Los doce meses de una categoría, precargados con el importe normal.

    Se guardan **solo los que difieren**. Si alguien pone el mismo numero en
    los doce, esta tabla se queda vacia y la categoria vuelve a ser un solo
    importe, que es como debe verse cuando no hay nada especial que decir.
    """

    GROUPS = (
        ("Primer semestre", [f"mes_{n}" for n in range(1, 7)]),
        ("Segundo semestre", [f"mes_{n}" for n in range(7, 13)]),
    )

    def __init__(self, *args, line=None, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.line = line
        self.household = household
        excepciones = line.overrides if line else {}
        for numero, nombre in enumerate(MESES, start=1):
            self.fields[f"mes_{numero}"] = forms.DecimalField(
                max_digits=16, decimal_places=2, min_value=0, required=False,
                label=nombre.capitalize(),
                initial=excepciones.get(numero, line.amount if line else None),
            )
        self._estilar()

    @transaction.atomic
    def save(self):
        from .models_plan import PlanLineMonth

        normal = self.line.amount
        for numero in range(1, 13):
            valor = self.cleaned_data.get(f"mes_{numero}")
            existente = PlanLineMonth.objects.filter(line=self.line,
                                                     month=numero).first()
            # Vacío o igual al normal: no es una excepción y no se guarda.
            if valor is None or valor == normal:
                if existente:
                    existente.delete()
                continue
            if existente:
                existente.amount = valor
                existente.save(update_fields=["amount", "updated_at"])
            else:
                PlanLineMonth.objects.create(
                    household=self.line.household, line=self.line,
                    month=numero, amount=valor)
        return self.line
