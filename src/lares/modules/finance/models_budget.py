"""Presupuestos por categoria.

Un presupuesto solo sirve si avisa a tiempo. Saber el 31 que te pasaste no
cambia nada; saberlo el 12, si. Por eso lo importante no es el total gastado,
sino el RITMO: llevas el 40% del mes y el 80% del presupuesto.
"""

from django.db import models

from lares.core.models import HouseholdScopedModel


class Budget(HouseholdScopedModel):
    account = models.ForeignKey(
        "core.Account", verbose_name="en qué", on_delete=models.CASCADE,
        related_name="budgets",
    )
    amount = models.DecimalField("cuánto al mes", max_digits=16, decimal_places=2)
    is_active = models.BooleanField("activo", default=True)
    note = models.CharField("nota", max_length=200, blank=True)

    class Meta:
        ordering = ["account__name"]
        verbose_name = "presupuesto"
        verbose_name_plural = "presupuestos"
        constraints = [
            models.UniqueConstraint(fields=["household", "account"],
                                    name="uniq_budget_account"),
        ]

    def __str__(self):
        return f"{self.account.name}: {self.amount}"
