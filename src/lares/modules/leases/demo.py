"""Los dos lados de la mesa, con un mes sin cobrar a proposito."""

import datetime as dt
from decimal import Decimal

from lares.core.models import Party
from lares.modules.property.models import Property

from .models import Lease
from .services import ensure_periods


def seed(household) -> str:
    hoy = dt.date.today()
    owner = Party.objects.filter(household=household, is_self=True).first()

    def parte(nombre, kind=Party.Kind.PERSON):
        p, _ = Party.objects.get_or_create(household=household, name=nombre,
                                           defaults={"kind": kind})
        return p

    # 1. Tu eres el inquilino: pagas.
    casa = Property.objects.filter(household=household,
                                   name="Casa de Providencia").first()
    if casa:
        contrato, _ = Lease.objects.get_or_create(
            household=household, property_ref=casa,
            direction=Lease.Direction.TENANT,
            defaults=dict(
                kind="lease", name="Renta de Providencia",
                counterpart=parte("Sr. Ramírez"),
                starts_on=hoy - dt.timedelta(days=265),
                ends_on=hoy + dt.timedelta(days=100),
                rent_amount=Decimal("18500"), rent_day=5,
                deposit_amount=Decimal("37000"), owner=owner, currency="MXN",
                increase_kind=Lease.Increase.PERCENT,
                increase_percent=Decimal("6.00"), increase_month=1,
                description="Entregada pintada, sin desperfectos. Fotos del "
                            "día de entrada en el expediente.",
            ),
        )
        _pagar_todo_menos(household, contrato, sin_pagar=0)

    # 2. Tu eres el arrendador: cobras, y este mes no ha llegado.
    depto = Property.objects.filter(household=household,
                                    name="Departamento en Chapalita").first()
    if depto:
        contrato, _ = Lease.objects.get_or_create(
            household=household, property_ref=depto,
            direction=Lease.Direction.LANDLORD,
            defaults=dict(
                kind="lease", name="Renta de Chapalita",
                counterpart=parte("Fernanda Ríos"),
                starts_on=hoy - dt.timedelta(days=420),
                ends_on=hoy + dt.timedelta(days=310),
                rent_amount=Decimal("14500"), rent_day=3,
                deposit_amount=Decimal("14500"), owner=owner, currency="MXN",
                increase_kind=Lease.Increase.INPC, increase_month=6,
                guarantor=parte("Ing. Ríos"),
                legal_policy="Póliza jurídica con Zurich, folio 88231",
                description="Entregado con cocina integral y clima. Inventario "
                            "firmado por ambas partes.",
            ),
        )
        _pagar_todo_menos(household, contrato, sin_pagar=2)

    return f"arrendamiento: {Lease.objects.count()} contratos"


def _pagar_todo_menos(household, lease, sin_pagar: int):
    """Marca como pagados todos los meses salvo los ultimos `sin_pagar`.

    Y los asienta en el libro, que es lo que hace el formulario de verdad. Sin
    esto la renta cobrada no aparece como ingreso en ninguna parte: ni en el
    flujo, ni en el rendimiento, ni en la base de impuestos.
    """
    from lares.core.models import Account, Entry, Posting

    ensure_periods(lease)
    banco, categoria = _cuentas_de(household, lease)

    meses = list(lease.payments.order_by("due_on"))
    corte = len(meses) - sin_pagar if sin_pagar else len(meses)
    for i, pago in enumerate(meses):
        if i >= corte or pago.paid_on:
            continue
        pago.paid_on = pago.due_on
        pago.amount_paid = pago.amount
        if banco and categoria:
            signo = 1 if lease.is_landlord else -1
            asiento = Entry.objects.create(
                household=household, date=pago.due_on, source="demo",
                description=f"Renta {pago.period} · {lease.property_ref.name}",
                counterparty=lease.counterpart,
            )
            inmueble = lease.property_ref.as_concrete()
            Posting.objects.create(household=household, entry=asiento,
                                   account=banco, amount=pago.amount * signo,
                                   currency=lease.currency or "MXN",
                                   dimension=inmueble)
            Posting.objects.create(household=household, entry=asiento,
                                   account=categoria, amount=-pago.amount * signo,
                                   currency=lease.currency or "MXN",
                                   dimension=inmueble)
            pago.entry = asiento
        pago.save(update_fields=["paid_on", "amount_paid", "entry", "updated_at"])


def _cuentas_de(household, lease):
    """La cuenta por la que entra o sale, y la categoría que le toca."""
    from lares.core.models import Account

    banco = Account.objects.filter(household=household,
                                   type=Account.Type.ASSET).first()
    if not banco:
        return None, None
    if lease.is_landlord:
        categoria, _ = Account.objects.get_or_create(
            household=household, name="Ingresos: renta",
            defaults={"type": Account.Type.INCOME, "currency": "MXN"})
    else:
        categoria, _ = Account.objects.get_or_create(
            household=household, name="Gastos: vivienda",
            defaults={"type": Account.Type.EXPENSE, "currency": "MXN"})
    return banco, categoria
