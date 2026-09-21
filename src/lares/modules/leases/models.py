"""Arrendamiento, en los dos sentidos.

Un inmueble que se renta deja de ser un gasto y pasa a ser un negocio pequeno:
hay un contrato, una contraparte, un cobro que puede no llegar, un deposito que
hay que devolver y un rendimiento que conviene saber.

Como en los prestamos, es un solo modelo con direccion. Hacer dos habria
duplicado el contrato, el deposito, el incremento anual, el acta de entrega y el
aviso de renovacion, que son identicos a ambos lados de la mesa. Lo unico que
cambia es quien cobra y quien paga.

    eres el arrendador  -> obligacion de COBRAR  -> el inmueble es tuyo
    eres el inquilino   -> obligacion de PAGAR   -> el inmueble no suma a tu
                                                    patrimonio, pero el deposito
                                                    que dejaste si es tuyo
"""

import datetime as dt
from decimal import Decimal

from django.db import models

from lares.core.models import HouseholdScopedModel, Resource

CENTAVO = Decimal("0.01")


class Lease(Resource):
    resource_kind = "lease"

    # Un contrato no se deja a nadie ni se extravía.
    can_be_lent = False
    can_be_checked = False

    class Direction(models.TextChoices):
        # El pronombre solo no basta: "lo rento" significa las dos cosas en
        # espanol. Las etiquetas dicen de quien es el inmueble y quien paga,
        # que es lo unico que no se puede malinterpretar.
        LANDLORD = "landlord", "Es mío y se lo rento a alguien"
        TENANT = "tenant", "No es mío, yo pago la renta"

    class Increase(models.TextChoices):
        NONE = "none", "Sin incremento pactado"
        PERCENT = "percent", "Un porcentaje fijo"
        INPC = "inpc", "Según la inflación (INPC)"

    direction = models.CharField("sentido", max_length=10,
                                 choices=Direction.choices,
                                 default=Direction.LANDLORD)
    property_ref = models.ForeignKey(
        "property.Property", verbose_name="de qué inmueble",
        on_delete=models.CASCADE, related_name="leases",
    )
    counterpart = models.ForeignKey(
        "core.Party", verbose_name="con quién", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leases",
    )

    starts_on = models.DateField("desde")
    ends_on = models.DateField("hasta", null=True, blank=True)

    # Desde cuando lleva Lares la cuenta de los meses. Va aparte de
    # `starts_on` porque son dos hechos distintos: cuando empezo el contrato
    # -que manda para el incremento anual y para la vigencia- y desde cuando
    # se controlan los cobros aqui.
    #
    # Sin esto, registrar un contrato de hace cuatro anos materializaba 48
    # meses sin cobrar y el detector de huecos gritaba una deuda de 432.000
    # que nadie debe. Lo anterior a esta fecha se dio por saldado fuera.
    tracked_from = models.DateField("llevar el control desde",
                                    null=True, blank=True)
    rent_amount = models.DecimalField("renta mensual", max_digits=12,
                                      decimal_places=2)
    rent_day = models.PositiveSmallIntegerField("día de pago", default=1)

    deposit_amount = models.DecimalField("depósito en garantía", max_digits=12,
                                         decimal_places=2, null=True, blank=True)
    deposit_returned_on = models.DateField("depósito devuelto el", null=True,
                                           blank=True)
    deposit_returned_amount = models.DecimalField(
        "devuelto", max_digits=12, decimal_places=2, null=True, blank=True)

    increase_kind = models.CharField("incremento anual", max_length=10,
                                     choices=Increase.choices,
                                     default=Increase.NONE)
    increase_percent = models.DecimalField("porcentaje", max_digits=5,
                                           decimal_places=2, null=True, blank=True)
    increase_month = models.PositiveSmallIntegerField(
        "mes del incremento", null=True, blank=True)

    guarantor = models.ForeignKey(
        "core.Party", verbose_name="fiador", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leases_guaranteed",
    )
    legal_policy = models.CharField("póliza jurídica", max_length=160, blank=True)

    class Meta:
        verbose_name = "contrato de arrendamiento"
        verbose_name_plural = "contratos de arrendamiento"

    def __str__(self):
        return self.name

    # -- Direccion -----------------------------------------------------------

    @property
    def is_landlord(self) -> bool:
        return self.direction == self.Direction.LANDLORD

    @property
    def counts_as_asset(self) -> bool:
        """Un contrato no es un bien.

        El inmueble ya cuenta por su lado; el deposito que dejaste tambien, y
        se lleva aparte para no mezclarlo con el contrato.
        """
        return False

    # -- Vigencia ------------------------------------------------------------

    @property
    def is_live(self) -> bool:
        hoy = dt.date.today()
        if self.status != self.Status.ACTIVE:
            return False
        if self.ends_on and self.ends_on < hoy:
            return False
        return self.starts_on <= hoy

    @property
    def days_to_end(self):
        return (self.ends_on - dt.date.today()).days if self.ends_on else None

    @property
    def next_increase(self):
        """Cuándo toca subir la renta, si se pactó."""
        if self.increase_kind == self.Increase.NONE or not self.increase_month:
            return None
        hoy = dt.date.today()
        cuando = dt.date(hoy.year, self.increase_month, 1)
        if cuando < hoy:
            cuando = dt.date(hoy.year + 1, self.increase_month, 1)
        return cuando

    # -- Deposito ------------------------------------------------------------

    @property
    def deposit_pending(self) -> Decimal:
        """Lo que falta por devolver o recuperar del depósito."""
        if not self.deposit_amount or self.deposit_returned_on:
            return Decimal(0)
        return self.deposit_amount

    # -- Cobros --------------------------------------------------------------

    def period_key(self, fecha: dt.date) -> str:
        return f"{fecha:%Y-%m}"

    @property
    def collected(self) -> Decimal:
        total = self.payments.aggregate(t=models.Sum("amount_paid"))["t"]
        return Decimal(total or 0)

    @property
    def overdue_payments(self) -> list:
        hoy = dt.date.today()
        return [p for p in self.payments.all() if p.is_late(hoy)]

    @property
    def months_covered(self) -> int:
        """Meses saldados. Uno abonado a medias no cuenta como cubierto."""
        return sum(1 for p in self.payments.all() if not p.shortfall)

    @property
    def role(self) -> str:
        """Tu papel en el contrato, en una palabra.

        La etiqueta del formulario explica el sentido a quien lo llena por
        primera vez; en una lista solo estorba.
        """
        return "Arriendas" if self.is_landlord else "Rentas"

    def context_line(self) -> str:
        partes = [
            self.role,
            str(self.counterpart) if self.counterpart else "",
            f"hasta {self.ends_on:%d/%m/%Y}" if self.ends_on else "sin fecha de fin",
        ]
        return ", ".join(p for p in partes if p)


class RentPayment(HouseholdScopedModel):
    """Un mes de renta: lo que tocaba y lo que de verdad se pagó."""

    lease = models.ForeignKey(Lease, on_delete=models.CASCADE,
                             related_name="payments")
    period = models.CharField("periodo", max_length=7, db_index=True)   # AAAA-MM
    due_on = models.DateField("vencía el")
    amount = models.DecimalField("lo que tocaba", max_digits=12, decimal_places=2)

    paid_on = models.DateField("pagado el", null=True, blank=True)
    amount_paid = models.DecimalField("lo que se pagó", max_digits=12,
                                      decimal_places=2, null=True, blank=True)
    entry = models.ForeignKey(
        "core.Entry", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="rent_payments",
    )
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-due_on"]
        verbose_name = "mes de renta"
        verbose_name_plural = "meses de renta"
        constraints = [
            models.UniqueConstraint(fields=["lease", "period"],
                                    name="uniq_rent_period"),
        ]

    def __str__(self):
        return f"{self.lease.name} · {self.period}"

    def is_late(self, on_date: dt.date | None = None) -> bool:
        """Vencido y sin saldar.

        Un abono parcial no salda el mes. Mirar solo la fecha de pago haria
        desaparecer del radar justo el caso que mas se pierde: el inquilino que
        abona la mitad y nadie vuelve a reclamar el resto.
        """
        return bool(self.shortfall) and self.due_on < (on_date or dt.date.today())

    def days_late(self, on_date: dt.date | None = None) -> int:
        hoy = on_date or dt.date.today()
        if self.paid_on and not self.shortfall:
            return max((self.paid_on - self.due_on).days, 0)
        return max((hoy - self.due_on).days, 0)

    @property
    def shortfall(self) -> Decimal:
        """Lo que falta de este mes.

        Darlo por pagado sin anotar el importe se toma como pagado entero: lo
        contrario llenaria la pantalla de atrasos que no existen.
        """
        if self.paid_on and self.amount_paid is None:
            return Decimal(0)
        return max(self.amount - (self.amount_paid or Decimal(0)), Decimal(0))
