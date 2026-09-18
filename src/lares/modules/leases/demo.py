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
    """Marca como pagados todos los meses salvo los ultimos `sin_pagar`."""
    ensure_periods(lease)
    meses = list(lease.payments.order_by("due_on"))
    corte = len(meses) - sin_pagar if sin_pagar else len(meses)
    for i, pago in enumerate(meses):
        if i >= corte:
            continue
        pago.paid_on = pago.due_on
        pago.amount_paid = pago.amount
        pago.save(update_fields=["paid_on", "amount_paid", "updated_at"])
