"""Provisiones: dinero que ya tiene dueno aunque siga en la cuenta.

El saldo del banco miente. Si tienes 42.000 pero 9.000 son del predial de enero
y 15.000 de la colegiatura, tu disponible real son 18.000. Gastarte la
diferencia es el error que obliga a pedir prestado en enero.

Una provision no mueve dinero: lo aparta. Por eso no es un asiento -no hay
transaccion que registrar- sino una anotacion sobre una cuenta que ya existe.
"""

from decimal import Decimal

from django.db import models

from lares.core.models import HouseholdScopedModel


class Provision(HouseholdScopedModel):
    name = models.CharField("para qué", max_length=200)
    account = models.ForeignKey(
        "core.Account", verbose_name="en qué cuenta está", on_delete=models.CASCADE,
        related_name="provisions",
    )

    target_amount = models.DecimalField("cuánto hace falta", max_digits=16,
                                        decimal_places=2)
    saved_amount = models.DecimalField("cuánto llevas apartado", max_digits=16,
                                       decimal_places=2, default=0)
    due_on = models.DateField("para cuándo", null=True, blank=True)

    # De dónde salió la idea, si vino de una obligación con fecha e importe.
    source_key = models.CharField(max_length=200, blank=True, db_index=True)
    is_active = models.BooleanField("activa", default=True)
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["due_on", "name"]
        verbose_name = "provisión"
        verbose_name_plural = "provisiones"
        indexes = [models.Index(fields=["household", "is_active"])]

    def __str__(self):
        return self.name

    @property
    def missing(self):
        return max(self.target_amount - self.saved_amount, Decimal(0))

    @property
    def progress(self) -> float:
        if not self.target_amount:
            return 0.0
        return min(float(self.saved_amount / self.target_amount), 1.0)

    @property
    def monthly_needed(self):
        """Cuánto habría que apartar cada mes para llegar a tiempo."""
        import datetime as dt

        if not self.due_on or self.missing <= 0:
            return None
        meses = max(
            (self.due_on.year - dt.date.today().year) * 12
            + (self.due_on.month - dt.date.today().month),
            1,
        )
        return (self.missing / meses).quantize(Decimal("0.01"))
