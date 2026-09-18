"""Compras a meses.

Es la forma normal de comprar en Mexico y no encaja en ninguna de las dos
maneras obvias de registrarla:

    registrar el total      -> el sistema te pide pagar 12.000 este mes cuando
                               el banco solo te cobra 1.000
    registrar la mensualidad -> tu deuda real queda subestimada en 11.000

Las dos mienten en algo distinto. Lo correcto es separar dos cosas que no son
lo mismo:

    lo que DEBES        el total pendiente. Es deuda desde el dia uno.
    lo que TE COBRAN    solo la mensualidad que cayo en este corte.

Por eso el asiento registra el total -el patrimonio queda bien- y este modelo
dice que parte de ese saldo todavia no te la exigen.
"""

import datetime as dt
from decimal import Decimal

from django.db import models

from lares.core.models import HouseholdScopedModel

CENTAVO = Decimal("0.01")


class InstallmentPlan(HouseholdScopedModel):
    card = models.ForeignKey(
        "finance.CreditCard", verbose_name="con qué tarjeta",
        on_delete=models.CASCADE, related_name="installment_plans",
    )
    description = models.CharField("qué compraste", max_length=250)
    merchant = models.ForeignKey(
        "core.Party", verbose_name="dónde", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="installment_plans",
    )

    total_amount = models.DecimalField("total de la compra", max_digits=16,
                                       decimal_places=2)
    months = models.PositiveSmallIntegerField("en cuántos meses")
    first_charge_on = models.DateField("primer cargo")
    interest_free = models.BooleanField("sin intereses", default=True)
    # Lo que el banco te cobra cada mes. Con intereses NO es el total entre los
    # meses: incluye el interes, y la diferencia es lo que cuesta pagar a plazos.
    installment_amount = models.DecimalField(
        "mensualidad que te cobran", max_digits=16, decimal_places=2,
        null=True, blank=True,
    )

    entry = models.ForeignKey(
        "core.Entry", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="installment_plans",
    )
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        ordering = ["first_charge_on"]
        verbose_name = "compra a meses"
        verbose_name_plural = "compras a meses"
        indexes = [models.Index(fields=["household", "card", "is_active"])]

    def __str__(self):
        return f"{self.description} · {self.months} meses"

    @property
    def installment(self) -> Decimal:
        """Lo que te cobran cada mes.

        Sin intereses es el total entre los meses. Con intereses lo dice el
        banco, y por eso se guarda tal cual en vez de calcularlo: cada uno
        aplica su comision y su redondeo.
        """
        if self.installment_amount:
            return self.installment_amount
        if not self.months:
            return Decimal(0)
        return (self.total_amount / self.months).quantize(CENTAVO)

    @property
    def principal_per_month(self) -> Decimal:
        """La parte de cada mensualidad que baja la deuda de verdad."""
        if not self.months:
            return Decimal(0)
        return (self.total_amount / self.months).quantize(CENTAVO)

    @property
    def total_to_pay(self) -> Decimal:
        return (self.installment * self.months).quantize(CENTAVO)

    @property
    def interest_total(self) -> Decimal:
        """Lo que cuesta pagarlo a plazos. En una compra a MSI es cero."""
        return max(self.total_to_pay - self.total_amount, Decimal(0))

    @property
    def interest_share(self) -> float:
        """Qué proporción del precio se va en intereses."""
        if not self.total_amount:
            return 0.0
        return float(self.interest_total / self.total_amount)

    def charged_by(self, fecha: dt.date | None = None) -> int:
        """Cuántas mensualidades te han cobrado ya a esa fecha."""
        fecha = fecha or dt.date.today()
        if fecha < self.first_charge_on:
            return 0
        meses = ((fecha.year - self.first_charge_on.year) * 12
                 + (fecha.month - self.first_charge_on.month) + 1)
        return max(0, min(meses, self.months))

    def deferred_at(self, fecha: dt.date | None = None) -> Decimal:
        """Lo que sigue pendiente pero todavía no te exigen.

        Se calcula sobre el capital, no sobre la mensualidad: el libro registro
        el precio de la compra, no lo que acabaras pagando con intereses. Los
        intereses son un gasto de cada mes, no deuda de hoy.
        """
        pendientes = self.months - self.charged_by(fecha)
        return (self.principal_per_month * pendientes).quantize(CENTAVO)

    @property
    def remaining(self) -> Decimal:
        """Lo que te falta por pagar, con intereses incluidos."""
        pendientes = self.months - self.charged_by()
        return (self.installment * pendientes).quantize(CENTAVO)

    @property
    def ends_on(self) -> dt.date:
        total = self.first_charge_on.month - 1 + max(self.months - 1, 0)
        ano = self.first_charge_on.year + total // 12
        mes = total % 12 + 1
        import calendar

        return dt.date(ano, mes,
                       min(self.first_charge_on.day, calendar.monthrange(ano, mes)[1]))

    @property
    def is_finished(self) -> bool:
        return self.charged_by() >= self.months
