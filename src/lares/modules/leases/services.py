"""Lo que un contrato de arrendamiento permite saber.

Sobre todo una cosa que casi nadie calcula: cuanto renta de verdad un inmueble
despues de lo que cuesta tenerlo.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum

from lares.core.models import Account, Posting
from lares.core.scoping import use_household

from .models import Lease, RentPayment

CENTAVO = Decimal("0.01")


def ensure_periods(lease: Lease, until: dt.date | None = None) -> int:
    """Crea los meses de renta que faltan hasta hoy.

    Se materializan en vez de calcularse al vuelo porque un mes de renta tiene
    estado propio: se paga tarde, se paga a medias, se condona. Eso no cabe en
    una formula.

    Empieza en `tracked_from` y no en `starts_on` cuando esta puesto. Es la
    diferencia entre "el contrato empezo en 2022" -que sigue siendo verdad y
    manda para el incremento y la vigencia- y "de los cobros me encargo yo
    desde hoy". Sin esa distincion, dar de alta un contrato viejo inventaba
    cuarenta y ocho meses sin cobrar el primer dia.
    """
    import calendar

    hasta = until or dt.date.today()
    if lease.ends_on:
        hasta = min(hasta, lease.ends_on)

    desde = max(lease.starts_on, lease.tracked_from or lease.starts_on)

    creados = 0
    cursor = desde.replace(day=1)
    while cursor <= hasta:
        dia = min(lease.rent_day, calendar.monthrange(cursor.year, cursor.month)[1])
        vence = dt.date(cursor.year, cursor.month, dia)
        # El mes que vencio ANTES de empezar el control tampoco se crea, no
        # solo los anos anteriores. Poner el control hoy, dia 21, con la renta
        # del dia 5, no puede estrenarse con un mes ya en mora.
        if vence < desde:
            cursor = (cursor + dt.timedelta(days=32)).replace(day=1)
            continue
        _, nuevo = RentPayment.objects.get_or_create(
            household=lease.household, lease=lease, period=f"{cursor:%Y-%m}",
            defaults={"due_on": vence, "amount": lease.rent_amount},
        )
        creados += nuevo
        cursor = (cursor + dt.timedelta(days=32)).replace(day=1)

    limpiar_lo_anterior(lease, desde)
    return creados


def limpiar_lo_anterior(lease: Lease, desde: dt.date | None = None) -> int:
    """Borra los meses previos que el sistema invento y nadie toco.

    Hace falta porque el dano ya esta hecho cuando alguien pone la fecha: los
    48 meses existen desde que dio de alta el contrato, y una fecha que no los
    quita no arregla nada.

    Solo se van los que estan intactos. Un mes con cobro anotado o con asiento
    es un dato que alguien metio, y eso no se borra por mover una fecha: si
    estorba, se baja la fecha y vuelve a salir.
    """
    if not lease.tracked_from:
        return 0
    desde = desde or max(lease.starts_on, lease.tracked_from)
    borrados, _ = RentPayment.objects.filter(
        lease=lease, due_on__lt=desde,
        paid_on__isnull=True, amount_paid__isnull=True, entry__isnull=True,
    ).delete()
    return borrados


@dataclass(frozen=True)
class Yield:
    lease: object
    annual_rent: Decimal
    annual_costs: Decimal
    net: Decimal
    value: Decimal

    @property
    def cap_rate(self) -> float | None:
        """Lo que renta al año en proporción a lo que vale."""
        if not self.value:
            return None
        return float(self.net / self.value)

    @property
    def margin(self) -> float | None:
        if not self.annual_rent:
            return None
        return float(self.net / self.annual_rent)


def performance(household, months: int = 12) -> list:
    """Cuánto renta cada inmueble después de lo que cuesta tenerlo.

    La renta bruta engana: un inmueble que renta 15.000 al mes y se come 4.000
    en predial, mantenimiento y seguro no renta 15.000.
    """
    desde = dt.date.today() - dt.timedelta(days=months * 31)
    salida = []

    with use_household(household):
        for lease in Lease.objects.filter(status=Lease.Status.ACTIVE,
                                          direction=Lease.Direction.LANDLORD):
            cobrado = (
                RentPayment.objects.filter(
                    lease=lease, paid_on__isnull=False, paid_on__gte=desde
                ).aggregate(t=Sum("amount_paid"))["t"] or Decimal(0)
            )
            # Si aun no hay historial, se proyecta con la renta pactada.
            if not cobrado:
                cobrado = lease.rent_amount * 12

            costes = _costs_of(lease.property_ref, desde)
            valor = (lease.property_ref.current_value
                     or lease.property_ref.purchase_amount or Decimal(0))
            salida.append(Yield(lease=lease, annual_rent=cobrado,
                                annual_costs=costes, net=cobrado - costes,
                                value=valor))
    return sorted(salida, key=lambda y: -(y.cap_rate or 0))


def _costs_of(prop, desde: dt.date) -> Decimal:
    """Lo que costó tener ese inmueble, según el libro."""
    from lares.core.models.resource import Resource

    concreto = prop.as_concrete()
    tipos = {ContentType.objects.get_for_model(concreto.__class__).pk,
             ContentType.objects.get_for_model(Resource).pk}
    total = Posting.objects.filter(
        dimension_type__in=tipos, dimension_id=concreto.pk,
        account__type=Account.Type.EXPENSE, amount__gt=0,
        entry__date__gte=desde,
    ).aggregate(t=Sum("amount"))["t"]
    return total or Decimal(0)


def next_rent(lease: Lease) -> Decimal:
    """La renta después del incremento pactado.

    El INPC no se inventa: si no hay dato, se dice y se deja al usuario.
    """
    if lease.increase_kind == Lease.Increase.PERCENT and lease.increase_percent:
        factor = Decimal(1) + (lease.increase_percent / Decimal(100))
        return (lease.rent_amount * factor).quantize(CENTAVO)
    return lease.rent_amount
