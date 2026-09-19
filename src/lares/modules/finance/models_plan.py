"""Presupuesto: lo que piensas gastar, contra lo que gastaste.

No es lo mismo que un tope mensual y por eso no comparte modelo. Un tope dice
"no te pases este mes" y sirve para frenar; un presupuesto responde "voy como
pensaba" y sirve para decidir. Las dos preguntas hacen falta y se contestan con
datos distintos.

Dos cosas deciden si esto sirve o es un ejercicio contable:

  1. **La desviacion acumulada, no la del mes.** Un mes malo no dice nada; tres
     seguidos si. Por eso lo que se compara es la proyeccion de cierre contra
     lo previsto, y no el gasto del mes contra la doceava parte.
  2. **Partir de lo del ano pasado.** Planear desde cero es lo que hace que
     nadie repita el ejercicio al segundo ano.

Un proyecto -una obra, un viaje, una boda- se presupuesta igual, y es donde mas
se desvia. Lo unico que cambia es de donde sale el gasto real: en el anual, de
la categoria; en el proyecto, de lo que se atribuyo al proyecto con la misma
dimension del libro que sirve para saber cuanto te cuesta el coche.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import models

from lares.core.models import HouseholdScopedModel


class Plan(HouseholdScopedModel):
    class Kind(models.TextChoices):
        ANNUAL = "annual", "Del año"
        PROJECT = "project", "De un proyecto"

    name = models.CharField("cómo lo llamas", max_length=200)
    kind = models.CharField("de qué tipo", max_length=10, choices=Kind.choices,
                            default=Kind.ANNUAL)
    year = models.PositiveSmallIntegerField("ejercicio", null=True, blank=True)
    starts_on = models.DateField("desde", null=True, blank=True)
    ends_on = models.DateField("hasta", null=True, blank=True)
    currency = models.CharField("moneda", max_length=3, default="MXN")
    is_active = models.BooleanField("activo", default=True)
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-year", "name"]
        verbose_name = "presupuesto"
        verbose_name_plural = "presupuestos"
        indexes = [models.Index(fields=["household", "is_active"])]

    def __str__(self):
        return self.name

    @property
    def is_project(self) -> bool:
        return self.kind == self.Kind.PROJECT

    @property
    def period(self) -> tuple:
        """Desde y hasta, sea del año o de un proyecto."""
        if self.is_project:
            return (self.starts_on or self.created_at.date(),
                    self.ends_on or dt.date.today())
        ano = self.year or dt.date.today().year
        return dt.date(ano, 1, 1), dt.date(ano, 12, 31)

    @property
    def elapsed(self) -> float:
        """Qué parte del periodo ya pasó, de 0 a 1.

        De aqui sale la proyeccion, y por eso importa que sea honesta: en un
        periodo que no ha empezado devuelve 0 y no se proyecta nada, en vez de
        dividir entre casi cero y escupir una cifra absurda.
        """
        desde, hasta = self.period
        total = (hasta - desde).days + 1
        if total <= 0:
            return 1.0
        corridos = (dt.date.today() - desde).days + 1
        return min(max(corridos / total, 0.0), 1.0)

    @property
    def is_over(self) -> bool:
        return self.elapsed >= 1.0

    @property
    def planned(self) -> Decimal:
        """Lo previsto para todo el periodo, sumando cadencias distintas."""
        return sum((linea.period_amount for linea in self.lines.all()),
                   Decimal(0))

    def context_line(self) -> str:
        desde, hasta = self.period
        if self.is_project:
            return f"Proyecto, {desde:%m/%Y} a {hasta:%m/%Y}"
        return f"Del año {self.year}"


class PlanLine(HouseholdScopedModel):
    """Una categoría del presupuesto y lo que piensas gastar en ella.

    La cadencia existe porque no todo el gasto se comporta igual, y forzar una
    sola forma estropea la mitad de los casos:

        al mes    el super, la gasolina: se gastan parejo y lo util es frenar
                  dentro del mes ("llevas el 80% con el 40% del mes corrido")
        en total  las vacaciones, el mantenimiento del coche: caen de golpe una
                  o dos veces al ano, y un tope mensual sobre ellas no significa
                  nada

    Es **una sola cifra por categoria**. Llevar aparte un tope mensual y un
    previsto anual seria decir dos veces lo mismo, y en cuanto uno se ajusta y
    el otro no, los dos dejan de ser fiables.
    """

    class Cadence(models.TextChoices):
        MONTHLY = "monthly", "Al mes"
        TOTAL = "total", "En todo el periodo"

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE,
                            related_name="lines")
    account = models.ForeignKey(
        "core.Account", verbose_name="en qué", on_delete=models.CASCADE,
        related_name="plan_lines",
    )
    amount = models.DecimalField("previsto", max_digits=16, decimal_places=2)
    cadence = models.CharField("cada cuánto", max_length=10,
                               choices=Cadence.choices, default=Cadence.MONTHLY)
    note = models.CharField("nota", max_length=200, blank=True)

    class Meta:
        ordering = ["account__name"]
        verbose_name = "línea del presupuesto"
        verbose_name_plural = "líneas del presupuesto"
        constraints = [
            models.UniqueConstraint(fields=["plan", "account"],
                                    name="uniq_plan_account"),
        ]

    def __str__(self):
        return f"{self.account.name}: {self.amount}"

    @property
    def is_monthly(self) -> bool:
        return self.cadence == self.Cadence.MONTHLY

    @property
    def months(self) -> int:
        desde, hasta = self.plan.period
        return max((hasta.year - desde.year) * 12
                   + (hasta.month - desde.month) + 1, 1)

    @property
    def period_amount(self) -> Decimal:
        """Lo previsto para todo el periodo, venga dicho al mes o de golpe."""
        if self.is_monthly:
            return self.amount * self.months
        return self.amount
