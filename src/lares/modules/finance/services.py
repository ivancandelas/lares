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
    from .models_income import RecurringIncome

    hoy = dt.date.today()
    datos = available(household)
    saldo = datos["available"]

    with use_household(household):
        # Un sueldo declarado no es una estimacion: se sabe cuanto es y cuando
        # cae. Solo cuando no hay ninguno se recurre al promedio, que depende
        # de si el mes pasado hubo un ingreso raro.
        declarados = [i for i in RecurringIncome.objects.filter(is_active=True)
                      if i.is_live]
        if declarados:
            mensual_estimado = sum((i.per_month for i in declarados),
                                   Decimal(0))
            origen_ingreso = "declarado"
        else:
            desde = hoy - dt.timedelta(days=92)
            ingreso = -(Posting.objects.filter(
                account__type=Account.Type.INCOME, amount__lt=0,
                entry__date__gte=desde
            ).aggregate(t=Sum("amount"))["t"] or 0)
            mensual_estimado = ((ingreso / 3).quantize(Decimal("0.01"))
                                if ingreso else Decimal(0))
            origen_ingreso = "promedio"

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
        "income_source": origen_ingreso,
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
    """El ritmo del mes, sobre las categorías presupuestadas al mes.

    Sale del mismo presupuesto y no de una tabla aparte: llevar un tope mensual
    por un lado y un previsto anual por otro seria decir dos veces lo mismo, y
    en cuanto uno se ajusta y el otro no, los dos dejan de ser fiables.
    """
    from .models_plan import Plan, PlanLine

    hoy = on_date or dt.date.today()
    primero = hoy.replace(day=1)
    siguiente = (primero + dt.timedelta(days=32)).replace(day=1)
    dias_mes = (siguiente - primero).days
    transcurrido = hoy.day / dias_mes

    with use_household(household):
        activos = list(
            PlanLine.objects.filter(
                plan__is_active=True, plan__kind=Plan.Kind.ANNUAL,
                plan__year=hoy.year, cadence=PlanLine.Cadence.MONTHLY,
            ).select_related("account", "plan")
        )
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


# ---------------------------------------------------------------------------
# Patrimonio neto y salud financiera
# ---------------------------------------------------------------------------


def net_worth(household) -> dict:
    """Lo que tienes menos lo que debes, sin contar nada dos veces.

    Los dos sitios donde es facil equivocarse:

      - una tarjeta ya es una cuenta de pasivo; sumar ademas "la tarjeta como
        cosa" la contaria dos veces
      - un prestamo que TE dieron no es un recurso tuyo, pero su saldo si es
        deuda; uno que TU diste es un activo y ya cuenta como recurso
    """
    from lares.core.models.resource import Resource

    with use_household(household):
        recursos = [r.as_concrete() for r in
                    Resource.objects.filter(status=Resource.Status.ACTIVE)]
        bienes = sum(
            (r.current_value or r.purchase_amount or Decimal(0))
            for r in recursos if r.counts_as_asset
        )
        en_cuentas = sum(
            a.balance for a in Account.objects.filter(
                type=Account.Type.ASSET, is_active=True)
        )
        deuda_cuentas = sum(
            a.balance for a in Account.objects.filter(
                type=Account.Type.LIABILITY, is_active=True)
        )
        deuda_prestamos = _borrowed_outstanding(recursos)

    activo = bienes + en_cuentas
    pasivo = deuda_cuentas + deuda_prestamos
    return {
        "goods": bienes,
        "in_accounts": en_cuentas,
        "assets": activo,
        "account_debt": deuda_cuentas,
        "loan_debt": deuda_prestamos,
        "liabilities": pasivo,
        "net": activo - pasivo,
    }


def _borrowed_outstanding(recursos) -> Decimal:
    """Lo que queda por pagar de los préstamos que te dieron."""
    total = Decimal(0)
    for recurso in recursos:
        if recurso.kind != "loan":
            continue
        if getattr(recurso, "is_mine_to_collect", True):
            continue        # los que diste ya cuentan como bien
        total += recurso.outstanding
    return total


def health(household, months: int = 3) -> dict:
    """Cuatro indicadores que dicen mas que cualquier grafica.

    Todos se calculan sobre lo registrado; lo que no este en el libro no
    aparece, y eso se dice en pantalla en vez de disimularlo.
    """
    hoy = dt.date.today()
    desde = hoy - dt.timedelta(days=months * 31)
    patrimonio = net_worth(household)
    disponible = available(household)["available"]

    with use_household(household):
        ingreso = -(Posting.objects.filter(
            account__type=Account.Type.INCOME, amount__lt=0, entry__date__gte=desde
        ).aggregate(t=Sum("amount"))["t"] or Decimal(0))
        gasto = Posting.objects.filter(
            account__type=Account.Type.EXPENSE, amount__gt=0, entry__date__gte=desde
        ).aggregate(t=Sum("amount"))["t"] or Decimal(0)

    ingreso_mes = (ingreso / months).quantize(Decimal("0.01"))
    gasto_mes = (gasto / months).quantize(Decimal("0.01"))
    fijo = _fixed_monthly(household)

    return {
        "months": months,
        "net": patrimonio["net"],
        "assets": patrimonio["assets"],
        "liabilities": patrimonio["liabilities"],
        "monthly_income": ingreso_mes,
        "monthly_spend": gasto_mes,
        "fixed_monthly": fijo,
        # Cuantos meses aguantas si dejara de entrar dinero manana.
        "runway": (disponible / gasto_mes) if gasto_mes else None,
        # Cuanto de lo que entra se queda.
        "savings_rate": (float((ingreso_mes - gasto_mes) / ingreso_mes)
                         if ingreso_mes else None),
        # Cuanto pesa la deuda frente a lo que ganas en un ano.
        "debt_to_income": (float(patrimonio["liabilities"] / (ingreso_mes * 12))
                           if ingreso_mes else None),
        # Que parte del ingreso ya esta comprometida antes de empezar el mes.
        "fixed_share": float(fijo / ingreso_mes) if ingreso_mes else None,
    }


def _fixed_monthly(household) -> Decimal:
    """Lo que se paga todos los meses pase lo que pase."""
    total = Decimal(0)
    with use_household(household):
        try:
            from lares.modules.subscriptions.models import Subscription

            total += sum(
                (s.monthly_cost or Decimal(0))
                for s in Subscription.objects.filter(
                    status=Subscription.Status.ACTIVE)
            )
        except ImportError:
            pass

        from .models import CreditCard

        # Una compra a meses es un pago fijo mas, aunque no sea una suscripcion.
        total += sum(
            (c.monthly_installments for c in CreditCard.objects.filter(
                status=CreditCard.Status.ACTIVE)),
            Decimal(0),
        )

        from lares.core.models.resource import Resource

        for recurso in Resource.objects.filter(status=Resource.Status.ACTIVE,
                                               kind="loan"):
            prestamo = recurso.as_concrete()
            if (not prestamo.is_mine_to_collect and prestamo.payment_amount
                    and not prestamo.is_settled):
                total += prestamo.payment_amount
    return total.quantize(Decimal("0.01"))
