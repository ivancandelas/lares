import datetime as dt

from django import forms
from django.db import transaction

from lares.core.forms import LaresForm, ResourceForm
from lares.core.models import Account, Entry, Posting

from .models import Lease, RentPayment


class LeaseForm(ResourceForm):
    """El alta de un contrato que puede llevar anos firmado.

    De aqui salio el peor primer dia posible: alguien registra el contrato de
    su casa en renta, que empezo en 2022, y la pantalla le recibe con 48 meses
    sin cobrar y una deuda de 432.000 que nadie debe. El sistema no se habia
    equivocado -nadie le dijo que los cuatro anos anteriores ya estaban
    cobrados- pero el efecto es que no te puedes creer nada de lo que ves.
    """

    GROUPS = (
        ("Qué contrato es", ["name", "direction", "property_ref", "counterpart"]),
        ("Vigencia y renta", ["starts_on", "ends_on", "rent_amount", "rent_day",
                              "currency", "tracked_from"]),
        ("Depósito", ["deposit_amount", "deposit_returned_on",
                      "deposit_returned_amount"]),
        ("Incremento anual", ["increase_kind", "increase_percent",
                              "increase_month"]),
        ("Garantías", ["guarantor", "legal_policy", "status"]),
        ("Acta de entrega y notas", ["description"]),
    )

    class Meta:
        model = Lease
        fields = ["name", "direction", "property_ref", "counterpart",
                  "starts_on", "ends_on", "rent_amount", "rent_day", "currency",
                  "tracked_from",
                  "deposit_amount", "deposit_returned_on",
                  "deposit_returned_amount", "increase_kind", "increase_percent",
                  "increase_month", "guarantor", "legal_policy", "status",
                  "description"]
        labels = {
            "name": "Cómo lo llamas",
            "direction": "Sentido",
            "property_ref": "De qué inmueble",
            "counterpart": "Con quién",
            "starts_on": "Desde",
            "ends_on": "Hasta",
            "tracked_from": "Llevar el control desde",
            "rent_amount": "Renta mensual",
            "rent_day": "Día de pago",
            "currency": "Moneda",
            "deposit_amount": "Depósito en garantía",
            "deposit_returned_on": "Devuelto el",
            "deposit_returned_amount": "Importe devuelto",
            "increase_kind": "Incremento anual",
            "increase_percent": "Porcentaje",
            "increase_month": "Mes del incremento",
            "guarantor": "Fiador",
            "legal_policy": "Póliza jurídica",
            "status": "Estado",
            "description": "Acta de entrega y notas",
        }
        help_texts = {
            "direction": "«Se lo rento a alguien» es cuando tú eres el inquilino.",
            "ends_on": "Avisa con 90 días: renovar o mudarse lleva su tiempo.",
            "rent_day": "De aquí sale el cobro o el pago de cada mes.",
            "tracked_from": "Lo anterior a esta fecha se da por saldado fuera "
                            "de aquí. Si el contrato viene de años atrás, "
                            "déjala en hoy: si no, aparecerán como sin cobrar "
                            "todos los meses desde que empezó.",
            "deposit_amount": "Sin registrarlo, recuperarlo depende de la memoria.",
            "increase_month": "El incremento pactado se pierde si nadie lo aplica.",
            "description": "Cómo estaba al entrar. Vale más que cualquier "
                           "discusión al salir.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_new:
            # Hoy por defecto, y no la fecha del contrato: quien registra un
            # contrato viejo casi nunca quiere reconstruir su historia de
            # cobros, y quien si la quiere solo tiene que bajar la fecha. El
            # que se equivoca en un sentido pierde un campo; en el otro, la
            # confianza en la pantalla.
            self.fields["tracked_from"].initial = dt.date.today

    def clean(self):
        datos = super().clean()
        if (datos.get("increase_kind") == Lease.Increase.PERCENT
                and not datos.get("increase_percent")):
            self.add_error("increase_percent", "Di qué porcentaje se pactó.")
        if datos.get("increase_kind") != Lease.Increase.NONE \
                and not datos.get("increase_month"):
            self.add_error("increase_month", "Di en qué mes toca.")
        return datos


class RentPaymentForm(LaresForm):
    """Registrar un mes de renta cobrado o pagado.

    Si se indica la cuenta, ademas del registro se hace el asiento: un cobro
    que no llega al libro no aparece en el rendimiento ni en el flujo.
    """

    account = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False,
        label="En qué cuenta entró o de cuál salió",
        help_text="Si la dejas vacía solo se marca como pagado, sin asiento.",
    )
    category = forms.ModelChoiceField(
        queryset=Account.objects.none(), required=False,
        label="Categoría", help_text="Ingresos por renta, o gasto de vivienda.",
    )

    class Meta:
        model = RentPayment
        fields = ["paid_on", "amount_paid", "note"]
        labels = {
            "paid_on": "Cuándo",
            "amount_paid": "Cuánto",
            "note": "Nota",
        }

    def __init__(self, *args, payment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.payment = payment or self.instance
        self.fields["paid_on"].initial = dt.date.today()
        if self.payment and self.payment.amount:
            self.fields["amount_paid"].initial = self.payment.amount
        if self.household:
            cuentas = Account._base_manager.filter(household=self.household,
                                                   is_active=True)
            self.fields["account"].queryset = cuentas.filter(
                type__in=[Account.Type.ASSET, Account.Type.LIABILITY])
            es_cobro = self.payment and self.payment.lease.is_landlord
            tipo = Account.Type.INCOME if es_cobro else Account.Type.EXPENSE
            self.fields["category"].queryset = cuentas.filter(type=tipo)

    @transaction.atomic
    def save(self, commit=True):
        pago = super().save(commit=commit)
        if not commit:
            return pago

        cuenta = self.cleaned_data.get("account")
        categoria = self.cleaned_data.get("category")
        if cuenta and categoria and not pago.entry:
            lease = pago.lease
            importe = pago.amount_paid or pago.amount
            asiento = Entry.objects.create(
                household=lease.household, date=pago.paid_on,
                description=f"Renta {pago.period} · {lease.property_ref.name}",
                source="lease", counterparty=lease.counterpart,
            )
            signo = 1 if lease.is_landlord else -1
            Posting.objects.create(household=lease.household, entry=asiento,
                                   account=cuenta, amount=importe * signo,
                                   dimension=lease.property_ref.as_concrete())
            Posting.objects.create(household=lease.household, entry=asiento,
                                   account=categoria, amount=-importe * signo,
                                   dimension=lease.property_ref.as_concrete())
            pago.entry = asiento
            pago.save(update_fields=["entry", "updated_at"])
        return pago
