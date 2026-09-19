import datetime as dt

from django import forms
from django.db import transaction

from lares.core.forms import LaresForm
from lares.core.models import Account, Entry, Posting

from .models import Goal, GoalContribution


class GoalForm(LaresForm):
    GROUPS = (
        ("Qué quieres", ["name", "kind", "target_amount", "currency"]),
        ("Para cuándo", ["target_on", "started_on", "baseline_amount"]),
        ("De dónde sale el dinero", ["account", "provision"]),
        ("Notas", ["note", "is_active"]),
    )

    class Meta:
        model = Goal
        fields = ["name", "kind", "target_amount", "currency", "target_on",
                  "started_on", "baseline_amount", "account", "provision",
                  "note", "is_active"]
        labels = {
            "name": "Qué quieres",
            "kind": "De qué tipo",
            "target_amount": "A cuánto quieres llegar",
            "currency": "Moneda",
            "target_on": "Para cuándo",
            "started_on": "Desde cuándo",
            "baseline_amount": "De cuánto partías",
            "account": "En qué cuenta",
            "provision": "Apartado en",
            "note": "Nota",
            "is_active": "Activa",
        }
        help_texts = {
            "target_on": "Sin fecha hay progreso, pero no hay proyección: "
                         "nadie puede decirte si vas tarde.",
            "baseline_amount": "Lo que ya tenías juntado, o lo que debías, el "
                               "día que empezaste.",
            "target_amount": "Para una deuda, normalmente cero.",
            "account": "Para una deuda es obligatoria: el avance se mide con "
                       "el saldo, no con los abonos.",
            "provision": "Atarla a una provisión aparta el dinero de verdad y "
                         "deja de contar como disponible.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.household:
            cuentas = Account._base_manager.filter(household=self.household,
                                                   is_active=True)
            self.fields["account"].queryset = cuentas.filter(
                type__in=[Account.Type.ASSET, Account.Type.LIABILITY])
            from lares.modules.finance.models_provision import Provision
            self.fields["provision"].queryset = Provision._base_manager.filter(
                household=self.household, is_active=True)

    def clean(self):
        datos = super().clean()
        if datos.get("kind") == Goal.Kind.PAYOFF and not datos.get("account"):
            self.add_error("account", "Di qué deuda: el avance se lee del saldo.")
        if (datos.get("kind") == Goal.Kind.SAVE
                and not datos.get("target_amount")):
            self.add_error("target_amount", "Una meta de ahorro necesita cifra.")
        return datos


class ContributionForm(LaresForm):
    """Apartar dinero para una meta.

    Si se dicen las dos cuentas, ademas se hace el asiento: apartar sin que el
    libro se entere deja el disponible real inflado, que es justo lo que este
    sistema existe para evitar.
    """

    account = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False,
        label="De qué cuenta sale",
        help_text="Si la dejas vacía solo se anota el avance, sin asiento.",
    )
    destination = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False,
        label="A qué cuenta va",
    )

    class Meta:
        model = GoalContribution
        fields = ["date", "amount", "note"]
        labels = {"date": "Cuándo", "amount": "Cuánto", "note": "Nota"}

    def __init__(self, *args, goal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.goal = goal
        self.fields["date"].initial = dt.date.today()
        if goal and goal.monthly_needed:
            self.fields["amount"].initial = goal.monthly_needed
        if self.household:
            self.fields["account"].queryset = Account._base_manager.filter(
                household=self.household, is_active=True,
                type__in=[Account.Type.ASSET, Account.Type.LIABILITY])
            self.fields["destination"].queryset = self.fields["account"].queryset
            if goal and goal.account:
                self.fields["destination"].initial = goal.account

    @transaction.atomic
    def save(self, commit=True):
        aporte = super().save(commit=False)
        aporte.goal = self.goal
        aporte.household = self.goal.household
        if not commit:
            return aporte
        aporte.save()

        origen = self.cleaned_data.get("account")
        destino = self.cleaned_data.get("destination")
        if origen and destino and origen != destino:
            asiento = Entry.objects.create(
                household=self.goal.household, date=aporte.date,
                description=f"Aportación a {self.goal.name}", source="goal",
            )
            Posting.objects.create(household=self.goal.household, entry=asiento,
                                   account=origen, amount=-aporte.amount,
                                   currency=self.goal.currency)
            Posting.objects.create(household=self.goal.household, entry=asiento,
                                   account=destino, amount=aporte.amount,
                                   currency=self.goal.currency)
            aporte.entry = asiento
            aporte.save(update_fields=["entry", "updated_at"])

        # Si la meta cuelga de una provision, apartar de verdad es esto: subir
        # lo reservado para que deje de contar como disponible.
        provision = self.goal.provision
        if provision:
            provision.saved_amount = provision.saved_amount + aporte.amount
            provision.save(update_fields=["saved_amount", "updated_at"])
        return aporte
