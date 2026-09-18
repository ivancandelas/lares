"""Lo que el libro permite responder y una tabla de movimientos no.

Tres preguntas, tres calculos:

    "¿cuanto de lo que hay en el banco es mio para gastar?"   -> disponible real
    "¿cuanto me cuesta de verdad tener esto?"                 -> coste total
    "¿me alcanza en marzo?"                                   -> proyeccion
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Sum
from django.utils.formats import date_format

from lares.core.models import Account, Obligation, Posting
from lares.core.models.resource import Resource
from lares.core.scoping import use_household

from .models_provision import Provision

# ---------------------------------------------------------------------------
# Disponible real
# ---------------------------------------------------------------------------


def available(household) -> dict:
    """Lo que hay, lo que ya tiene dueño, y lo que queda de verdad."""
    with use_household(household):
        liquidas = [a for a in Account.objects.filter(
            type=Account.Type.ASSET, is_active=True)]
        en_cuentas = sum(a.balance for a in liquidas)

        provisiones = list(Provision.objects.filter(is_active=True))
        apartado = sum(p.saved_amount for p in provisiones)
        comprometido = sum(p.target_amount for p in provisiones)

    return {
        "in_accounts": en_cuentas,
        "reserved": apartado,
        "committed": comprometido,
        # Lo apartado ya no es tuyo para gastar, aunque siga en la misma cuenta.
        "available": en_cuentas - apartado,
        "provisions": provisiones,
        "shortfall": max(comprometido - apartado, Decimal(0)),
    }


def suggest_provisions(household, months: int = 12) -> list:
    """Propone provisiones a partir de lo que ya se sabe que viene.

    No hay que adivinar nada: las obligaciones ya traen fecha e importe. Lo que
    hay que acertar es CUALES merecen provision, y el criterio es uno:

        una provision es para lo que no cabe en el mes en que cae.

    Por eso se descartan dos cosas:

      - lo que se repite cada mes (luz, renta, la tarjeta): eso es flujo, se
        paga del ingreso del mes y apartar para ello seria contarlo dos veces
      - lo pequeno frente a lo que entra: apartar 49 pesos no cambia nada y
        llena la pantalla de ruido
    """
    hoy = dt.date.today()
    limite = hoy + dt.timedelta(days=months * 31)

    with use_household(household):
        ya_provisionado = set(
            Provision.objects.filter(is_active=True).values_list("source_key", flat=True)
        )
        candidatas = list(
            Obligation.objects
            .filter(status=Obligation.Status.PENDING, amount__isnull=False,
                    due_on__gt=hoy, due_on__lte=limite)
            .exclude(amount=0)
            .order_by("due_on")
        )

        # Cada cuanto se repite cada cosa. Contar ocurrencias no sirve: el
        # motor solo materializa dos por delante, asi que lo mensual y lo anual
        # aparecen las mismas veces. Lo que las distingue es la distancia.
        fechas: dict = {}
        for o in candidatas:
            fechas.setdefault(_serie(o), []).append(o.due_on)
        periodo = {serie: _min_gap(dias) for serie, dias in fechas.items()}

        desde = hoy - dt.timedelta(days=92)
        ingreso = -(Posting.objects.filter(
            account__type=Account.Type.INCOME, amount__lt=0, entry__date__gte=desde
        ).aggregate(t=Sum("amount"))["t"] or 0)

    minimo = (ingreso / 12) if ingreso else Decimal(1000)

    utiles = [
        o for o in candidatas
        if o.dedupe_key not in ya_provisionado
        and (o.due_on - hoy).days >= 45
        and (periodo.get(_serie(o)) or 999) > 45
        and o.amount >= minimo
    ]
    # Lo más caro primero: es donde apartar cambia algo.
    return sorted(utiles, key=lambda o: -o.amount)[:10]


def _serie(obligation) -> tuple:
    """Identifica «la misma cosa que se repite», al margen del mes."""
    return (obligation.source, obligation.subject_id)


def _min_gap(fechas: list) -> int | None:
    """Días entre una ocurrencia y la siguiente. Un mes o menos es flujo."""
    if len(fechas) < 2:
        return None
    ordenadas = sorted(fechas)
    return min((b - a).days for a, b in zip(ordenadas, ordenadas[1:], strict=False))


# ---------------------------------------------------------------------------
# Coste total de propiedad
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostLine:
    label: str
    total: Decimal
    count: int


def cost_of(resource, months: int = 12) -> dict:
    """Cuánto te cuesta de verdad tener algo.

    Sale del libro, que es la única fuente que no cuenta nada dos veces. Los
    trabajos de mantenimiento que nadie asentó se listan aparte: fingir que
    también cuentan sería sumar lo mismo por dos caminos.
    """
    concreto = resource.as_concrete()
    desde = dt.date.today() - dt.timedelta(days=months * 31)

    # Se aceptan los dos tipos: los apuntes viejos pueden apuntar al padre.
    tipos = {ContentType.objects.get_for_model(concreto.__class__).pk}
    if concreto.__class__ is not Resource:
        tipos.add(ContentType.objects.get_for_model(Resource).pk)

    # El hogar sale del propio recurso: asi la funcion sirve tambien fuera de
    # una peticion -una tarea, la consola- sin devolver cero en silencio.
    with use_household(concreto.household):
        apuntes = Posting.objects.filter(
            dimension_type__in=tipos,
            dimension_id=concreto.pk,
            account__type=Account.Type.EXPENSE,
            amount__gt=0,
            entry__date__gte=desde,
        )
        por_categoria = list(
            apuntes.values("account__name")
            .annotate(total=Sum("amount"), n=Count("id"))
            .order_by("-total")
        )
        sin_asentar = _unbooked_work(concreto, desde)

    lineas = [CostLine(d["account__name"], d["total"], d["n"]) for d in por_categoria]
    total = sum(x.total for x in lineas)

    return {
        "resource": concreto,
        "months": months,
        "total": total,
        "monthly": (total / months) if months else Decimal(0),
        "lines": lineas,
        "unbooked": sin_asentar,
    }


def _unbooked_work(resource, desde: dt.date) -> list:
    """Trabajos registrados en mantenimiento que no llegaron al libro."""
    try:
        from lares.modules.maintenance.models import WorkOrder
    except ImportError:
        return []

    return list(
        WorkOrder.objects.filter(
            subject_type=ContentType.objects.get_for_model(resource.__class__),
            subject_id=resource.pk, done_on__gte=desde, cost__isnull=False,
        )
    )


# ---------------------------------------------------------------------------
# Proyeccion de flujo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Month:
    label: str
    first_day: dt.date
    income: Decimal
    outgo: Decimal
    balance: Decimal
    items: list


def cash_flow(household, months: int = 6) -> dict:
    """«¿Me alcanza en marzo?»

    Suma lo que ya esta en la base: saldo de hoy, mas el ingreso que se repite,
    menos las obligaciones con fecha. El ingreso es una estimacion y se dice:
    el promedio de los ultimos tres meses.
    """
    hoy = dt.date.today()
    datos = available(household)
    saldo = datos["available"]

    with use_household(household):
        desde = hoy - dt.timedelta(days=92)
        ingreso = -(Posting.objects.filter(
            account__type=Account.Type.INCOME, amount__lt=0, entry__date__gte=desde
        ).aggregate(t=Sum("amount"))["t"] or 0)
        mensual_estimado = (ingreso / 3).quantize(Decimal("0.01")) if ingreso else Decimal(0)

        pendientes = list(
            Obligation.objects.filter(
                status__in=[Obligation.Status.PENDING, Obligation.Status.OVERDUE],
                amount__isnull=False, due_on__lte=hoy + dt.timedelta(days=months * 31),
            ).exclude(amount=0).order_by("due_on")
        )

    salida, cursor = [], hoy.replace(day=1)
    for _ in range(months):
        siguiente = (cursor + dt.timedelta(days=32)).replace(day=1)
        del_mes = [o for o in pendientes if cursor <= o.due_on < siguiente]
        gasto = sum(o.amount for o in del_mes)
        saldo = saldo + mensual_estimado - gasto
        salida.append(Month(
            # date_format respeta el idioma; strftime da los meses en inglés.
            label=date_format(cursor, "F Y"), first_day=cursor,
            income=mensual_estimado, outgo=gasto, balance=saldo,
            items=sorted(del_mes, key=lambda o: -o.amount)[:5],
        ))
        cursor = siguiente

    return {
        "start": datos["available"],
        "monthly_income": mensual_estimado,
        "months": salida,
        "worst": min(salida, key=lambda m: m.balance) if salida else None,
        "goes_negative": [m for m in salida if m.balance < 0],
    }


# ---------------------------------------------------------------------------
# Presupuestos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetLine:
    budget: object
    planned: Decimal
    spent: Decimal
    month_elapsed: float

    @property
    def remaining(self) -> Decimal:
        return self.planned - self.spent

    @property
    def used(self) -> float:
        return float(self.spent / self.planned) if self.planned else 0.0

    @property
    def over(self) -> bool:
        return self.spent > self.planned

    @property
    def ahead(self) -> bool:
        """Gastas más rápido que el mes: es lo que avisa a tiempo.

        Saber el 31 que te pasaste no cambia nada; saberlo el 12, sí.
        """
        return not self.over and self.used > self.month_elapsed + 0.15

    @property
    def projected(self) -> Decimal:
        """A este ritmo, cómo acaba el mes."""
        if self.month_elapsed <= 0:
            return self.spent
        return (self.spent / Decimal(str(self.month_elapsed))).quantize(Decimal("1"))


def budgets(household, on_date: dt.date | None = None) -> dict:
    from .models_budget import Budget

    hoy = on_date or dt.date.today()
    primero = hoy.replace(day=1)
    siguiente = (primero + dt.timedelta(days=32)).replace(day=1)
    dias_mes = (siguiente - primero).days
    transcurrido = hoy.day / dias_mes

    with use_household(household):
        activos = list(Budget.objects.filter(is_active=True).select_related("account"))
        gastado = {
            d["account_id"]: d["total"]
            for d in Posting.objects.filter(
                account__type=Account.Type.EXPENSE, amount__gt=0,
                entry__date__gte=primero, entry__date__lt=siguiente,
            ).values("account_id").annotate(total=Sum("amount"))
        }

    lineas = [
        BudgetLine(budget=b, planned=b.amount,
                   spent=gastado.get(b.account_id, Decimal(0)),
                   month_elapsed=transcurrido)
        for b in activos
    ]
    lineas.sort(key=lambda line: -line.used)

    return {
        "lines": lineas,
        "month": primero,
        "elapsed": transcurrido,
        "planned": sum(line.planned for line in lineas),
        "spent": sum(line.spent for line in lineas),
        "over": [line for line in lineas if line.over],
        "ahead": [line for line in lineas if line.ahead],
        # Lo que se gasta sin presupuesto no es cero: es lo que no estás mirando.
        "unbudgeted": _unbudgeted(household, primero, siguiente,
                                  {b.account_id for b in activos}),
    }


def _unbudgeted(household, desde, hasta, con_presupuesto: set) -> Decimal:
    with use_household(household):
        total = Posting.objects.filter(
            account__type=Account.Type.EXPENSE, amount__gt=0,
            entry__date__gte=desde, entry__date__lt=hasta,
        ).exclude(account_id__in=con_presupuesto).aggregate(t=Sum("amount"))["t"]
    return total or Decimal(0)
