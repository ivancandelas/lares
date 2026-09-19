"""Metas: lo que quieres que pase, y la cuenta de si vas a llegar.

Una provision aparta dinero para algo que YA SABES que viene -el predial de
enero-. Una meta es lo contrario: algo que QUIERES que pase y que no tiene fecha
impuesta por nadie. Cambiar de coche, el enganche de una casa, un viaje, quedar
libre de la tarjeta.

Lo que separa una meta util de una lista de deseos es la proyeccion. No "llevas
el 45%", sino "a este ritmo llegarias en noviembre de 2029, siete meses tarde".
Para eso hay que medir el ritmo REAL, y por eso las dos clases de meta se miden
de forma distinta a proposito:

    juntar   ->  por lo que de verdad apartaste   (las aportaciones)
    saldar   ->  por lo que de verdad sigues debiendo   (el saldo de la cuenta)

Medir una deuda por los abonos mentiria: si abonas 5.000 al mes y cargas 4.000,
el resumen diria que vas bien mientras la deuda no baja. El saldo no deja
mentir, porque ya trae descontado lo que volviste a gastar.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import models
from django.utils.functional import cached_property

from lares.core.models import HouseholdScopedModel

CENTAVO = Decimal("0.01")
VENTANA = 6          # meses que se miran para estimar el ritmo


def _suma_meses(fecha: dt.date, meses: int) -> dt.date:
    """Mismo dia, `meses` despues. El 31 cae al ultimo dia del mes corto."""
    import calendar

    total = fecha.month - 1 + meses
    ano, mes = fecha.year + total // 12, total % 12 + 1
    return dt.date(ano, mes, min(fecha.day, calendar.monthrange(ano, mes)[1]))


def _meses_entre(desde: dt.date, hasta: dt.date) -> int:
    return (hasta.year - desde.year) * 12 + (hasta.month - desde.month)


class Goal(HouseholdScopedModel):
    class Kind(models.TextChoices):
        SAVE = "save", "Juntar dinero"
        PAYOFF = "payoff", "Dejar de deber"

    name = models.CharField("qué quieres", max_length=200)
    kind = models.CharField("de qué tipo", max_length=10, choices=Kind.choices,
                            default=Kind.SAVE)

    target_amount = models.DecimalField("a cuánto quieres llegar", max_digits=16,
                                        decimal_places=2, default=0)
    target_on = models.DateField("para cuándo", null=True, blank=True)
    currency = models.CharField("moneda", max_length=3, default="MXN")

    account = models.ForeignKey(
        "core.Account", verbose_name="en qué cuenta", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="goals",
    )
    # Atar la meta a una provision es lo que convierte el proposito en dinero
    # apartado de verdad: deja de contar como disponible en el resto del sistema.
    provision = models.ForeignKey(
        "finance.Provision", verbose_name="apartado en", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="goals",
    )

    baseline_amount = models.DecimalField(
        "de cuánto partías", max_digits=16, decimal_places=2, default=0,
        help_text="Lo que ya tenías juntado, o lo que debías, al empezar.",
    )
    started_on = models.DateField("desde cuándo", default=dt.date.today)

    is_active = models.BooleanField("activa", default=True)
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["target_on", "name"]
        verbose_name = "meta"
        verbose_name_plural = "metas"
        indexes = [models.Index(fields=["household", "is_active"])]

    def __str__(self):
        return self.name

    # -- Dónde vas ------------------------------------------------------------

    @property
    def is_payoff(self) -> bool:
        return self.kind == self.Kind.PAYOFF

    @cached_property
    def contributed(self) -> Decimal:
        total = self.contributions.aggregate(t=models.Sum("amount"))["t"]
        return Decimal(total or 0)

    @cached_property
    def current(self) -> Decimal:
        """Cuánto llevas juntado, o cuánto sigues debiendo.

        La deuda se lee del saldo y no de los abonos: es lo unico que no se
        puede maquillar volviendo a gastar.
        """
        if self.is_payoff:
            return self.account.balance if self.account else self.baseline_amount
        return self.baseline_amount + self.contributed

    @cached_property
    def missing(self) -> Decimal:
        falta = (self.current - self.target_amount if self.is_payoff
                 else self.target_amount - self.current)
        return max(falta, Decimal(0))

    @cached_property
    def is_reached(self) -> bool:
        return self.missing <= 0

    @cached_property
    def progress(self) -> float:
        """De 0 a 1. Para una deuda, cuánto del camino ya recorriste."""
        if self.is_payoff:
            camino = self.baseline_amount - self.target_amount
            if camino <= 0:
                return 1.0
            avance = self.baseline_amount - self.current
            return min(max(float(avance / camino), 0.0), 1.0)
        if not self.target_amount:
            return 0.0
        return min(max(float(self.current / self.target_amount), 0.0), 1.0)

    # -- A qué ritmo ----------------------------------------------------------

    @property
    def months_elapsed(self) -> int:
        return max(_meses_entre(self.started_on, dt.date.today()), 0)

    @cached_property
    def pace(self) -> Decimal | None:
        """Cuánto avanzas al mes, según lo que de verdad pasó.

        Devuelve None cuando todavia no hay historial del que sacar un ritmo:
        inventar uno con dos semanas de datos daria una fecha que no significa
        nada, y una fecha inventada es peor que ninguna.
        """
        meses = self.months_elapsed
        if not meses:
            return None

        if self.is_payoff:
            avance = self.baseline_amount - self.current
        else:
            ventana = min(meses, VENTANA)
            desde = _suma_meses(dt.date.today(), -ventana)
            avance = Decimal(
                self.contributions.filter(date__gte=desde)
                .aggregate(t=models.Sum("amount"))["t"] or 0
            )
            meses = ventana

        if avance <= 0:
            return None
        return (avance / meses).quantize(CENTAVO)

    @cached_property
    def eta(self) -> dt.date | None:
        """Cuándo llegarías si sigues como vas."""
        import math

        ritmo = self.pace
        if self.is_reached:
            return dt.date.today()
        if not ritmo:
            return None
        return _suma_meses(dt.date.today(), math.ceil(self.missing / ritmo))

    @cached_property
    def months_late(self) -> int | None:
        """Meses de retraso contra la fecha que te pusiste. Negativo: te sobra."""
        if not self.target_on or not self.eta:
            return None
        return _meses_entre(self.target_on, self.eta)

    @cached_property
    def monthly_needed(self) -> Decimal | None:
        """Cuánto tendrías que apartar cada mes para llegar a tiempo."""
        if not self.target_on or self.is_reached:
            return None
        meses = max(_meses_entre(dt.date.today(), self.target_on), 1)
        return (self.missing / meses).quantize(CENTAVO)

    @cached_property
    def gap(self) -> Decimal | None:
        """Lo que le falta a tu ritmo actual para ser suficiente."""
        hace_falta, llevas = self.monthly_needed, self.pace
        if hace_falta is None:
            return None
        return max(hace_falta - (llevas or Decimal(0)), Decimal(0))

    @cached_property
    def last_movement(self) -> dt.date | None:
        ultima = self.contributions.order_by("-date").first()
        return ultima.date if ultima else None

    def context_line(self) -> str:
        partes = [self.get_kind_display()]
        if self.target_on:
            partes.append(f"para {self.target_on:%m/%Y}")
        if self.provision:
            partes.append(f"apartado en {self.provision.name}")
        elif self.account:
            partes.append(str(self.account))
        return ", ".join(partes)


class GoalContribution(HouseholdScopedModel):
    """Lo que de verdad apartaste, y cuándo.

    Se guarda aparte del saldo porque el ritmo solo se puede medir con fechas:
    sin historial no hay proyeccion, y sin proyeccion una meta es un deseo con
    un numero al lado.
    """

    goal = models.ForeignKey(Goal, on_delete=models.CASCADE,
                            related_name="contributions")
    date = models.DateField("cuándo", default=dt.date.today)
    amount = models.DecimalField("cuánto", max_digits=16, decimal_places=2)
    entry = models.ForeignKey(
        "core.Entry", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="goal_contributions",
    )
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "aportación"
        verbose_name_plural = "aportaciones"

    def __str__(self):
        return f"{self.goal.name} · {self.amount:,.0f}"
