"""Primitiva 7 - Dinero: libro de partida doble, no "tabla de transacciones".

Es la decision que mas dolor ahorra a mediano plazo. Una tabla mutable de
movimientos parece mas simple hasta que aparecen: transferencias entre cuentas
propias (contadas dos veces), reembolsos, pagos parciales, correcciones,
multi-moneda y saldos historicos que no cuadran.

Un asiento (Entry) agrupa apuntes (Posting) que suman cero. Nada se edita:
las correcciones son asientos inversos. Ver ADR-0006.

Cada Posting puede apuntar a cualquier entidad del grafo, y ahi esta la gracia:
etiquetar la gasolina contra el Mazda permite calcular el costo real de tener
el auto, no solo "cuanto gaste en gasolina".
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .base import HouseholdScopedModel


class Account(HouseholdScopedModel):
    class Type(models.TextChoices):
        ASSET = "asset", "Activo"
        LIABILITY = "liability", "Pasivo"
        INCOME = "income", "Ingreso"
        EXPENSE = "expense", "Gasto"
        EQUITY = "equity", "Patrimonio"

    name = models.CharField(max_length=120)
    type = models.CharField(max_length=20, choices=Type.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    currency = models.CharField(max_length=3, default="MXN")

    institution = models.ForeignKey(
        "core.Party", null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts"
    )
    # Nunca se guardan credenciales bancarias. Solo lo suficiente para
    # identificar la cuenta en un estado de cuenta.
    last_four = models.CharField(max_length=4, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["type", "name"]

    def __str__(self):
        return self.name


class Entry(HouseholdScopedModel):
    """Asiento. Inmutable una vez contabilizado."""

    date = models.DateField(db_index=True)
    description = models.CharField(max_length=300)
    source = models.CharField(max_length=80, blank=True)     # "cfdi", "csv", "manual"
    external_ref = models.CharField(max_length=200, blank=True, db_index=True)
    document = models.ForeignKey(
        "core.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="entries"
    )
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reversed_by"
    )

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "entries"

    def __str__(self):
        return f"{self.date} {self.description}"

    @property
    def is_balanced(self) -> bool:
        return sum(p.amount for p in self.postings.all()) == 0


class Posting(HouseholdScopedModel):
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="postings")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="postings")
    # Positivo = cargo, negativo = abono. La suma por asiento debe ser 0.
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, default="MXN")

    # Dimension analitica: contra que recurso, obligacion, parte o proyecto.
    dimension_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    dimension_id = models.UUIDField(null=True, blank=True)
    dimension = GenericForeignKey("dimension_type", "dimension_id")

    memo = models.CharField(max_length=300, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["household", "account"]),
            models.Index(fields=["household", "dimension_type", "dimension_id"]),
        ]
