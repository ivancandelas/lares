from django.db import models

from lares.core.models import Resource


class CreditCard(Resource):
    """Una tarjeta es dos cosas a la vez, y conviene no confundirlas.

    Como objeto es un Resource: tiene emisor, titular, estado y documentos.
    Como dinero es una cuenta de pasivo del libro (`account`), donde viven los
    movimientos. Separarlas permite que la tarjeta se cancele sin borrar el
    historial de lo que se gasto con ella.
    """

    resource_kind = "credit_card"

    issuer = models.ForeignKey(
        "core.Party", verbose_name="banco", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="issued_cards",
    )
    account = models.OneToOneField(
        "core.Account", verbose_name="cuenta", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="credit_card",
    )

    last_four = models.CharField("últimos 4 dígitos", max_length=4, blank=True)
    credit_limit = models.DecimalField("límite", max_digits=16, decimal_places=2,
                                       null=True, blank=True)

    # Dia del mes, no fecha: se repiten todos los meses.
    cut_day = models.PositiveSmallIntegerField("día de corte", null=True, blank=True)
    due_day = models.PositiveSmallIntegerField("día límite de pago", null=True, blank=True)
    apr = models.DecimalField("tasa anual (%)", max_digits=5, decimal_places=2,
                              null=True, blank=True)

    class Meta:
        verbose_name = "tarjeta"
        verbose_name_plural = "tarjetas"

    def __str__(self):
        base = self.name
        return f"{base} ····{self.last_four}" if self.last_four else base

    def context_line(self) -> str:
        partes = [
            f"Corta el {self.cut_day}" if self.cut_day else "",
            f"se paga el {self.due_day}" if self.due_day else "",
            f"te quedan {self.available:,.0f}" if self.available is not None else "",
        ]
        return ", ".join(p for p in partes if p)

    @property
    def available(self):
        if self.credit_limit is None or not self.account:
            return None
        return self.credit_limit - self.account.balance
