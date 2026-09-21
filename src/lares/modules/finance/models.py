from django.db import models

from lares.core.models import Resource

from .models_income import RecurringIncome  # noqa: F401
from .models_installment import InstallmentPlan  # noqa: F401
from .models_plan import Plan, PlanLine, PlanLineMonth  # noqa: F401
from .models_provision import Provision  # noqa: F401


class CreditCard(Resource):
    """Una tarjeta es dos cosas a la vez, y conviene no confundirlas.

    Como objeto es un Resource: tiene emisor, titular, estado y documentos.
    Como dinero es una cuenta de pasivo del libro (`account`), donde viven los
    movimientos. Separarlas permite que la tarjeta se cancele sin borrar el
    historial de lo que se gasto con ella.
    """

    resource_kind = "credit_card"

    # El plástico existe, pero prestarlo no es algo que convenga registrar como un gesto normal.
    can_be_lent = False
    can_be_checked = False

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

    # -- El ciclo de la tarjeta ---------------------------------------------
    #
    # Una tarjeta tiene dos fechas y casi nadie distingue lo que significan:
    #
    #     corte   se cierra el estado de cuenta. Lo comprado despues ya cuenta
    #             para el periodo siguiente.
    #     pago    la fecha limite. Pagar el saldo AL CORTE -no el de hoy- es lo
    #             unico que evita intereses.
    #
    # Confundir "saldo actual" con "pago para no generar intereses" es el error
    # que hace que alguien pague de mas o genere intereses sin entender por que.

    def last_cut(self, on_date=None):
        """El último corte ya ocurrido."""
        import calendar
        import datetime as _dt

        if not self.cut_day:
            return None
        hoy = on_date or _dt.date.today()
        dia = min(self.cut_day, calendar.monthrange(hoy.year, hoy.month)[1])
        corte = _dt.date(hoy.year, hoy.month, dia)
        if corte > hoy:
            mes, ano = (12, hoy.year - 1) if hoy.month == 1 else (hoy.month - 1, hoy.year)
            corte = _dt.date(ano, mes, min(self.cut_day, calendar.monthrange(ano, mes)[1]))
        return corte

    def next_due(self, on_date=None):
        """La fecha límite de pago del corte que ya cerró."""
        import calendar
        import datetime as _dt

        corte = self.last_cut(on_date)
        if not (corte and self.due_day):
            return None
        mes, ano = (1, corte.year + 1) if corte.month == 12 else (corte.month + 1,
                                                                 corte.year)
        limite = _dt.date(ano, mes, min(self.due_day, calendar.monthrange(ano, mes)[1]))
        # Si el día de pago cae antes que el de corte, es del mismo mes.
        if self.due_day > self.cut_day:
            limite = _dt.date(corte.year, corte.month,
                              min(self.due_day,
                                  calendar.monthrange(corte.year, corte.month)[1]))
        return limite

    def balance_at(self, fecha):
        """Saldo de la tarjeta a una fecha: lo que aparece en el corte."""
        from decimal import Decimal

        if not self.account:
            return Decimal(0)
        from django.db.models import Sum

        total = self.account.postings.filter(
            entry__date__lte=fecha
        ).aggregate(t=Sum("amount"))["t"] or Decimal(0)
        return -total       # un pasivo se muestra en positivo

    @property
    def deferred(self):
        """Lo que debes a meses y todavia no te exigen.

        El saldo de la tarjeta incluye el total de cada compra a meses, porque
        es deuda desde el primer dia. Pero el banco solo te cobra una
        mensualidad por corte: el resto no entra en el pago de este mes.
        """
        from decimal import Decimal

        corte = self.last_cut()
        if not corte:
            return Decimal(0)
        planes = self.installment_plans.filter(is_active=True)
        return sum((p.deferred_at(corte) for p in planes), Decimal(0))

    @property
    def monthly_installments(self):
        """Lo que se te va cada mes en compras a meses, hasta que acaben."""
        from decimal import Decimal

        planes = [p for p in self.installment_plans.filter(is_active=True)
                  if not p.is_finished]
        return sum((p.installment for p in planes), Decimal(0))

    @property
    def no_interest_payment(self):
        """Lo que hay que pagar para no generar intereses.

        Es el saldo AL CORTE menos lo diferido a meses. Pagar el saldo entero
        adelantaria mensualidades que nadie te ha pedido; pagar de menos genera
        intereses sobre todo el periodo, no solo sobre la diferencia.
        """
        corte = self.last_cut()
        if not corte:
            return None
        return self.balance_at(corte) - self.deferred

    @property
    def after_cut(self):
        """Lo comprado después del corte: cuenta para el periodo siguiente."""
        corte = self.last_cut()
        if not (corte and self.account):
            return None
        return self.account.balance - self.balance_at(corte)

    @property
    def usage(self):
        """Qué proporción del límite llevas usada."""
        if not (self.credit_limit and self.account):
            return None
        return float(self.account.balance / self.credit_limit)
