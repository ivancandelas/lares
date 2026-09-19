"""Ingresos que se repiten: el sueldo, una pensión, una iguala.

Hasta ahora el flujo los adivinaba con el promedio de los ultimos tres meses,
que es lo unico que se puede hacer sin preguntar. Sirve, pero un sueldo no es
una estimacion: se sabe cuanto es y que dia cae. Declararlo cambia dos cosas
que importan mas de lo que parece:

  - la proyeccion deja de depender de si el mes pasado hubo un ingreso raro
  - se puede decir **cuanto queda** al mes, que es la unica cifra que la gente
    de verdad quiere: lo que entra menos lo que se va solo

No genera una obligacion. Cobrar el sueldo no es algo que tengas que hacer, y
llenar la lista de pendientes con cosas que pasan solas es la forma mas rapida
de que nadie la mire.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import models

from lares.core.models import HouseholdScopedModel


class RecurringIncome(HouseholdScopedModel):
    class Cycle(models.TextChoices):
        WEEKLY = "weekly", "Cada semana"
        BIWEEKLY = "biweekly", "Cada quincena"
        MONTHLY = "monthly", "Cada mes"
        BIMONTHLY = "bimonthly", "Cada dos meses"
        QUARTERLY = "quarterly", "Cada tres meses"
        SEMIANNUAL = "semiannual", "Cada seis meses"
        YEARLY = "yearly", "Cada año"

    name = models.CharField("qué es", max_length=200)
    payer = models.ForeignKey(
        "core.Party", verbose_name="quién te paga", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="incomes_paid",
    )
    amount = models.DecimalField("cuánto te llega", max_digits=16,
                                 decimal_places=2)
    cycle = models.CharField("cada cuánto", max_length=12,
                             choices=Cycle.choices, default=Cycle.MONTHLY)
    pay_day = models.PositiveSmallIntegerField("día de pago", null=True,
                                               blank=True)
    account = models.ForeignKey(
        "core.Account", verbose_name="dónde entra", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="incomes",
    )
    category = models.ForeignKey(
        "core.Account", verbose_name="cómo se clasifica", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="incomes_categorised",
    )
    currency = models.CharField("moneda", max_length=3, default="MXN")
    started_on = models.DateField("desde cuándo", null=True, blank=True)
    ends_on = models.DateField("hasta cuándo", null=True, blank=True)
    is_active = models.BooleanField("activo", default=True)
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-amount"]
        verbose_name = "ingreso recurrente"
        verbose_name_plural = "ingresos recurrentes"
        indexes = [models.Index(fields=["household", "is_active"])]

    def __str__(self):
        return self.name

    @property
    def is_live(self) -> bool:
        hoy = dt.date.today()
        if not self.is_active:
            return False
        if self.ends_on and self.ends_on < hoy:
            return False
        return not self.started_on or self.started_on <= hoy

    @property
    def per_month(self) -> Decimal:
        """Lo que representa al mes, sea cual sea su ciclo.

        La quincena no es medio mes exacto -son 24 pagas al ano, no 24 medios
        meses- pero para proyectar a meses la diferencia no cambia ninguna
        decision y evita inventar un calendario aparte.
        """
        veces = {"weekly": 52, "biweekly": 24, "monthly": 12, "bimonthly": 6,
                 "quarterly": 4, "semiannual": 2, "yearly": 1}
        return (self.amount * veces.get(self.cycle, 12) / 12).quantize(
            Decimal("0.01"))

    def next_on(self, on_date: dt.date | None = None) -> dt.date | None:
        """El próximo día de cobro, si se sabe qué día cae."""
        import calendar

        hoy = on_date or dt.date.today()
        if not self.pay_day:
            return None
        dia = min(self.pay_day, calendar.monthrange(hoy.year, hoy.month)[1])
        proximo = dt.date(hoy.year, hoy.month, dia)
        if proximo >= hoy:
            return proximo
        mes = hoy.month % 12 + 1
        ano = hoy.year + (1 if mes == 1 else 0)
        return dt.date(ano, mes,
                       min(self.pay_day, calendar.monthrange(ano, mes)[1]))
