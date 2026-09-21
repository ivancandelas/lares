"""Prestamos, en los dos sentidos.

Casi todo el software de finanzas personales asume que solo DEBES dinero. Pero
prestarle a un hermano, dar un anticipo o vender algo a plazos son igual de
reales, y son justo los que se olvidan: no llega un recibo cada mes que te lo
recuerde.

Por eso es un solo modelo con direccion, como el contrato de arrendamiento.
Hacer dos habria duplicado el saldo, la amortizacion, el interes, el calendario
y el estado.

    te lo dieron  -> obligacion de pagar   -> pasivo
    lo diste      -> obligacion de cobrar  -> activo
"""

import datetime as dt
from decimal import Decimal

from django.db import models

from lares.core.models import HouseholdScopedModel, Resource

CENTAVO = Decimal("0.01")


class Loan(Resource):
    resource_kind = "loan"

    # Prestar un préstamo no significa nada.
    can_be_lent = False
    can_be_checked = False

    class Direction(models.TextChoices):
        BORROWED = "borrowed", "Me lo prestaron"
        LENT = "lent", "Lo presté"

    class Interest(models.TextChoices):
        NONE = "none", "Sin intereses"
        FLAT = "flat", "Interés fijo sobre el saldo"
        AMORTIZED = "amortized", "Amortizado (cuota fija)"

    class State(models.TextChoices):
        CURRENT = "current", "Al corriente"
        LATE = "late", "Atrasado"
        PAID = "paid", "Pagado"
        FORGIVEN = "forgiven", "Perdonado"

    direction = models.CharField("sentido", max_length=10, choices=Direction.choices,
                                 default=Direction.BORROWED)
    counterpart = models.ForeignKey(
        "core.Party", verbose_name="con quién", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="loans",
    )

    principal = models.DecimalField("importe original", max_digits=16,
                                    decimal_places=2)
    interest_kind = models.CharField("intereses", max_length=12,
                                     choices=Interest.choices, default=Interest.NONE)
    annual_rate = models.DecimalField("tasa anual (%)", max_digits=6, decimal_places=3,
                                      null=True, blank=True)

    started_on = models.DateField("desde cuándo", null=True, blank=True)
    term_months = models.PositiveSmallIntegerField("plazo en meses", null=True,
                                                   blank=True)
    payment_amount = models.DecimalField("cuota", max_digits=16, decimal_places=2,
                                         null=True, blank=True)
    payment_day = models.PositiveSmallIntegerField("día de pago", null=True,
                                                   blank=True)

    state = models.CharField("estado del préstamo", max_length=12,
                             choices=State.choices, default=State.CURRENT)
    # Un prestamo de palabra es el que de verdad se pierde de vista.
    is_informal = models.BooleanField("sin contrato", default=False)

    class Meta:
        verbose_name = "préstamo"
        verbose_name_plural = "préstamos"

    def __str__(self):
        return self.name

    # -- Dinero --------------------------------------------------------------

    @property
    def paid(self) -> Decimal:
        """Lo que se ha abonado al capital, no lo pagado en total."""
        total = self.payments.aggregate(
            t=models.Sum("principal_part"))["t"] or Decimal(0)
        return Decimal(total)

    @property
    def interest_paid(self) -> Decimal:
        total = self.payments.aggregate(
            t=models.Sum("interest_part"))["t"] or Decimal(0)
        return Decimal(total)

    @property
    def outstanding(self) -> Decimal:
        if self.state in (self.State.PAID, self.State.FORGIVEN):
            return Decimal(0)
        return max(self.principal - self.paid, Decimal(0))

    @property
    def progress(self) -> float:
        if not self.principal:
            return 0.0
        return min(float(self.paid / self.principal), 1.0)

    @property
    def is_settled(self) -> bool:
        return self.outstanding <= 0

    # -- Direccion -----------------------------------------------------------

    @property
    def is_mine_to_collect(self) -> bool:
        return self.direction == self.Direction.LENT

    @property
    def counts_as_asset(self) -> bool:
        """Lo que te deben es tuyo; lo que debes, no."""
        return (super().counts_as_asset and self.is_mine_to_collect
                and not self.is_settled)

    # -- Calendario ----------------------------------------------------------

    @property
    def last_payment_on(self):
        ultimo = self.payments.order_by("-date").first()
        return ultimo.date if ultimo else None

    @property
    def months_silent(self) -> int | None:
        """Cuánto lleva sin moverse. Es lo que delata un préstamo olvidado."""
        referencia = self.last_payment_on or self.started_on
        if not referencia or self.is_settled:
            return None
        hoy = dt.date.today()
        return (hoy.year - referencia.year) * 12 + (hoy.month - referencia.month)

    def amortization(self, limit: int = 60) -> list:
        """Tabla de amortización, cuando hay cuota e interés.

        Se calcula en vez de guardarse: una tabla almacenada deja de cuadrar en
        cuanto alguien adelanta un pago.
        """
        if not (self.payment_amount and self.term_months):
            return []

        tasa = (self.annual_rate or 0) / Decimal(1200) \
            if self.interest_kind != self.Interest.NONE else Decimal(0)
        saldo = self.principal
        inicio = self.started_on or dt.date.today()
        filas = []

        for periodo in range(1, min(self.term_months, limit) + 1):
            interes = (saldo * tasa).quantize(CENTAVO)
            capital = min(self.payment_amount - interes, saldo)
            if capital <= 0:
                break
            saldo = (saldo - capital).quantize(CENTAVO)
            filas.append({
                "n": periodo,
                "date": _add_months(inicio, periodo),
                "payment": (capital + interes).quantize(CENTAVO),
                "principal": capital,
                "interest": interes,
                "balance": saldo,
            })
            if saldo <= 0:
                break
        return filas

    def save(self, *args, **kwargs):
        """Mantiene sincronizado el valor heredado de Resource.

        Un prestamo vale lo que queda por cobrar, no su importe original. Se
        guarda en el campo en vez de calcularlo al vuelo porque `current_value`
        es un campo del modelo padre: sobrescribirlo con una propiedad rompe a
        Django antes de que exista la clave primaria.
        """
        super().save(*args, **kwargs)
        objetivo = self.outstanding if self.is_mine_to_collect else None
        if self.current_value != objetivo:
            type(self).all_objects.filter(pk=self.pk).update(current_value=objetivo)
            self.current_value = objetivo

    def context_line(self) -> str:
        partes = [
            self.get_direction_display(),
            str(self.counterpart) if self.counterpart else "",
            "sin contrato" if self.is_informal else "",
        ]
        return ", ".join(p for p in partes if p)


class LoanPayment(HouseholdScopedModel):
    """Un abono. Separar capital de intereses es lo que hace que el saldo baje."""

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="payments")
    date = models.DateField("cuándo", db_index=True)
    amount = models.DecimalField("cuánto", max_digits=16, decimal_places=2)
    principal_part = models.DecimalField("a capital", max_digits=16,
                                         decimal_places=2, default=0)
    interest_part = models.DecimalField("a intereses", max_digits=16,
                                        decimal_places=2, default=0)
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "abono"
        verbose_name_plural = "abonos"
        indexes = [models.Index(fields=["household", "loan", "-date"])]

    def __str__(self):
        return f"{self.date}: {self.amount}"

    def save(self, *args, **kwargs):
        # Sin desglose, todo va a capital: es lo correcto en los préstamos de
        # palabra, que son la mayoría de los que alguien registra a mano.
        if not self.principal_part and not self.interest_part:
            self.principal_part = self.amount
        super().save(*args, **kwargs)
        # El saldo del prestamo cambia con cada abono.
        self.loan.save(update_fields=None)


def _add_months(fecha: dt.date, meses: int) -> dt.date:
    import calendar

    total = fecha.month - 1 + meses
    ano = fecha.year + total // 12
    mes = total % 12 + 1
    return dt.date(ano, mes, min(fecha.day, calendar.monthrange(ano, mes)[1]))
