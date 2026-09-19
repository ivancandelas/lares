"""Previsto contra real, y a dónde va a acabar el año."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum

from lares.core.models import Account, Posting
from lares.core.scoping import use_household

from .models_plan import Plan, PlanLine

CENTAVO = Decimal("0.01")
MARGEN = Decimal("0.10")        # lo que se considera "ir como pensabas"


@dataclass
class Line:
    account: object
    planned: Decimal          # lo previsto para TODO el periodo
    actual: Decimal
    elapsed: float
    line: object = None       # la línea, cuando la hay: dice su cadencia

    @property
    def variance(self) -> Decimal:
        """Lo que llevas de más (positivo) o de menos (negativo)."""
        return self.actual - self.planned

    @property
    def projection(self) -> Decimal | None:
        """A dónde llega a cierre si sigues así.

        Es una regla de tres sobre el tiempo transcurrido: cruda, pero es la
        unica que no exige inventar un patron de gasto que nadie conoce. Se
        presenta siempre como proyeccion, no como dato.
        """
        if not self.elapsed:
            return None
        return (self.actual / Decimal(str(self.elapsed))).quantize(CENTAVO)

    @property
    def projected_variance(self) -> Decimal | None:
        proyectado = self.projection
        return None if proyectado is None else proyectado - self.planned

    @property
    def is_drifting(self) -> bool:
        """Se va a pasar de verdad, no es un mes malo."""
        desviacion = self.projected_variance
        if desviacion is None or not self.planned:
            return False
        return desviacion > self.planned * MARGEN

    @property
    def progress(self) -> float:
        if not self.planned:
            return 1.0 if self.actual else 0.0
        return min(max(float(self.actual / self.planned), 0.0), 1.0)


@dataclass
class Report:
    plan: object
    lines: list
    unplanned: list          # gasto real en categorías que nadie presupuestó

    @property
    def planned(self) -> Decimal:
        return sum((x.planned for x in self.lines), Decimal(0))

    @property
    def actual(self) -> Decimal:
        return (sum((x.actual for x in self.lines), Decimal(0))
                + sum((x.actual for x in self.unplanned), Decimal(0)))

    @property
    def variance(self) -> Decimal:
        return self.actual - self.planned

    @property
    def projection(self) -> Decimal | None:
        if not self.plan.elapsed:
            return None
        return (self.actual / Decimal(str(self.plan.elapsed))).quantize(CENTAVO)

    @property
    def projected_variance(self) -> Decimal | None:
        proyectado = self.projection
        return None if proyectado is None else proyectado - self.planned


def _spent_by_account(plan) -> dict:
    """Lo gastado por categoría en el periodo, en una sola consulta.

    Una consulta por linea parece inofensiva hasta que el tablero corre los
    checks de todos los presupuestos y son cientos. Como el agrupado hace falta
    igual para saber que se gasto FUERA del presupuesto, sale gratis.

    En un proyecto solo cuenta lo que se le atribuyo explicitamente: si no, la
    obra de la cocina se comeria todo el gasto de "casa" del ano.
    """
    desde, hasta = plan.period
    qs = Posting.objects.filter(entry__date__gte=desde, entry__date__lte=hasta)
    if plan.is_project:
        qs = qs.filter(dimension_type=ContentType.objects.get_for_model(Plan),
                       dimension_id=plan.pk)
    filas = qs.values("account").annotate(t=Sum("amount"))
    # Los ingresos viven en negativo; los gastos, en positivo.
    return {f["account"]: abs(Decimal(f["t"] or 0)) for f in filas}


def report(household, plan) -> Report:
    with use_household(household):
        gastado = _spent_by_account(plan)
        propias = list(plan.lines.select_related("account"))
        lineas = [
            Line(account=linea.account, planned=linea.period_amount,
                 actual=gastado.get(linea.account_id, Decimal(0)),
                 elapsed=plan.elapsed, line=linea)
            for linea in propias
        ]

        # Lo que se gastó fuera del presupuesto: es donde se escapa el dinero
        # de quien presupuesta solo lo que ya sabe que va a gastar.
        previstas = {x.account_id for x in propias}
        sueltas = []
        if not plan.is_project:
            fuera = [pk for pk, total in gastado.items()
                     if pk not in previstas and total]
            cuentas = {
                a.pk: a for a in Account.objects.filter(
                    pk__in=fuera, type=Account.Type.EXPENSE)
            }
            sueltas = [
                Line(account=cuentas[pk], planned=Decimal(0),
                     actual=gastado[pk], elapsed=plan.elapsed)
                for pk in fuera if pk in cuentas
            ]
        sueltas.sort(key=lambda x: -x.actual)

    lineas.sort(key=lambda x: -(x.projected_variance or Decimal(0)))
    return Report(plan=plan, lines=lineas, unplanned=sueltas)


def seed_from(household, plan, year: int) -> int:
    """Rellena el presupuesto con lo que de verdad se gastó en un año.

    Planear desde cero es lo que hace que nadie repita el ejercicio al segundo
    ano; partir de lo que ya pasó convierte media hora en cinco minutos.
    """
    import datetime as dt

    desde, hasta = dt.date(year, 1, 1), dt.date(year, 12, 31)
    creadas = 0
    with use_household(household):
        ya = set(plan.lines.values_list("account_id", flat=True))
        gastadas = (
            Posting.objects.filter(
                account__type=Account.Type.EXPENSE,
                entry__date__gte=desde, entry__date__lte=hasta,
            ).values("account").annotate(t=Sum("amount"))
        )
        for fila in gastadas:
            if fila["account"] in ya or not fila["t"]:
                continue
            # Lo que se sabe es el TOTAL del ano, asi que se guarda como tal.
            # Dejarlo como mensual lo multiplicaria por doce sin que se note.
            PlanLine.objects.create(
                household=household, plan=plan, account_id=fila["account"],
                amount=abs(Decimal(fila["t"])).quantize(CENTAVO),
                cadence=PlanLine.Cadence.TOTAL,
                note=f"Partiendo de lo gastado en {year}",
            )
            creadas += 1
    return creadas
