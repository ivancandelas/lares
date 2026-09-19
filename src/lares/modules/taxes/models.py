"""Impuestos: organizar lo que hace falta para declarar, no declarar.

**Lo que este modulo no hace: presentar tu declaracion.** Eso lo hace el SAT o
tu contador, y competir con ellos seria meterse en un terreno regulado donde un
error tiene consecuencias legales y ninguna ventaja.

Lo que si hace es el trabajo real de cada abril, que es de organizacion:

    que te toca y cuando   por regimen, con el mismo motor de obligaciones
    que es deducible       marcar un CFDI que ya entro por la bandeja
    cuanto llevas          la BASE, con lo registrado, siempre como estimacion
    el paquete             facturas, retenciones y resumen, en un archivo

Sobre el alcance del calculo, que es donde este modulo podria hacer dano: se
calcula la **base gravable** -ingresos menos deducciones- porque es aritmetica
y se puede auditar. El ISR con tarifa progresiva NO se calcula: sus tablas
cambian cada ano y equivocarse sale caro. La unica excepcion es RESICO, cuya
tasa es fija por tramo de ingreso (art. 113-E LISR) y no ha cambiado desde 2022.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import models

from lares.core.models import HouseholdScopedModel

CENTAVO = Decimal("0.01")


class TaxProfile(HouseholdScopedModel):
    """Quién declara y bajo qué régimen.

    Es por persona y no por hogar: en una casa puede haber alguien asalariado y
    alguien con actividad empresarial, y no les toca ni lo mismo ni cuando.
    """

    class Regime(models.TextChoices):
        SALARIES = "salaries", "Sueldos y salarios"
        RESICO = "resico", "RESICO (simplificado de confianza)"
        BUSINESS = "business", "Actividad empresarial y profesional"
        LEASE = "lease", "Arrendamiento"
        PLATFORMS = "platforms", "Plataformas tecnológicas"
        OTHER = "other", "Otro"

    taxpayer = models.ForeignKey(
        "core.Party", verbose_name="quién declara", on_delete=models.CASCADE,
        related_name="tax_profiles",
    )
    regime = models.CharField("régimen", max_length=20, choices=Regime.choices,
                              default=Regime.SALARIES)
    rfc = models.CharField("RFC", max_length=13, blank=True)
    started_on = models.DateField("desde cuándo", null=True, blank=True)

    # El tope de las deducciones personales es el MENOR entre el 15% de tus
    # ingresos y cinco UMA anuales. El 15% es una formula; la UMA es un numero
    # que el SAT publica cada febrero, asi que se pide en vez de inventarse.
    uma_annual = models.DecimalField(
        "UMA anual del ejercicio", max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text="El SAT la publica cada febrero. Sin ella no se aplica ese tope.",
    )

    is_active = models.BooleanField("activo", default=True)
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["taxpayer__name"]
        verbose_name = "perfil fiscal"
        verbose_name_plural = "perfiles fiscales"

    def __str__(self):
        return f"{self.taxpayer} · {self.get_regime_display()}"

    @property
    def files_monthly(self) -> bool:
        return self.regime in (self.Regime.RESICO, self.Regime.BUSINESS,
                               self.Regime.LEASE, self.Regime.PLATFORMS)

    @property
    def blind_deduction(self) -> Decimal | None:
        """La «deducción ciega» del arrendamiento: 35% sin comprobar nada.

        Art. 115 LISR. Se puede optar por ella en vez de deducir gastos reales,
        y encima se suma el predial. Para casi todo el mundo sale mejor, y casi
        nadie lo sabe.
        """
        return Decimal("0.35") if self.regime == self.Regime.LEASE else None


class Deduction(HouseholdScopedModel):
    """Algo que pagaste y que baja lo que declaras.

    Apunta al documento en vez de copiar sus datos: la factura ya entro por la
    bandeja con su RFC, su fecha y su importe, y duplicarlos aqui abriria la
    puerta a que digan cosas distintas.
    """

    class Kind(models.TextChoices):
        MEDICAL = "medical", "Médicos, dentales y hospitalarios"
        MEDICAL_INSURANCE = "medical_insurance", "Seguro de gastos médicos"
        FUNERAL = "funeral", "Gastos funerarios"
        DONATION = "donation", "Donativos"
        MORTGAGE = "mortgage", "Intereses reales de hipoteca"
        RETIREMENT = "retirement", "Aportaciones para el retiro"
        TUITION = "tuition", "Colegiaturas"
        SCHOOL_TRANSPORT = "school_transport", "Transporte escolar obligatorio"
        SAVINGS = "savings", "Depósitos en cuentas para el ahorro"
        BUSINESS = "business", "Gasto deducible de la actividad"

    profile = models.ForeignKey(TaxProfile, verbose_name="de quién",
                               on_delete=models.CASCADE, related_name="deductions")
    kind = models.CharField("de qué tipo", max_length=24, choices=Kind.choices,
                            default=Kind.MEDICAL)
    document = models.ForeignKey(
        "core.Document", verbose_name="con qué factura", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deductions",
    )
    entry = models.ForeignKey(
        "core.Entry", verbose_name="qué movimiento", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deductions",
    )
    description = models.CharField("concepto", max_length=250, blank=True)
    amount = models.DecimalField("importe", max_digits=16, decimal_places=2)
    date = models.DateField("fecha", default=dt.date.today)
    beneficiary = models.ForeignKey(
        "core.Party", verbose_name="a nombre de quién", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deductions_received",
    )
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "deducción"
        verbose_name_plural = "deducciones"
        indexes = [models.Index(fields=["household", "date"])]
        constraints = [
            # El mismo documento no puede deducirse dos veces: es la forma mas
            # facil de inflar una declaracion sin darse cuenta.
            models.UniqueConstraint(
                fields=["profile", "document"], name="uniq_deduccion_documento",
                condition=models.Q(document__isnull=False),
            ),
        ]

    def __str__(self):
        return self.description or self.get_kind_display()

    @property
    def year(self) -> int:
        return self.date.year

    @property
    def is_personal(self) -> bool:
        """Las personales topan; las de la actividad, no."""
        return self.kind != self.Kind.BUSINESS


class Withholding(HouseholdScopedModel):
    """Impuesto que alguien ya te retuvo y enteró por ti.

    Existe para no pagarlo dos veces, que es el error que mas dinero cuesta de
    los que se cometen solos: la retencion ya se fue, pero si no se declara,
    se paga otra vez.
    """

    class Kind(models.TextChoices):
        ISR = "isr", "ISR"
        IVA = "iva", "IVA"

    profile = models.ForeignKey(TaxProfile, verbose_name="de quién",
                               on_delete=models.CASCADE,
                               related_name="withholdings")
    kind = models.CharField("qué impuesto", max_length=5, choices=Kind.choices,
                            default=Kind.ISR)
    payer = models.ForeignKey(
        "core.Party", verbose_name="quién retuvo", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="withholdings_made",
    )
    document = models.ForeignKey(
        "core.Document", verbose_name="con qué comprobante", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="withholdings",
    )
    amount = models.DecimalField("importe retenido", max_digits=16,
                                 decimal_places=2)
    date = models.DateField("fecha", default=dt.date.today)
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "retención"
        verbose_name_plural = "retenciones"
        indexes = [models.Index(fields=["household", "date"])]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.amount:,.2f}"


class Filing(HouseholdScopedModel):
    """Una declaración presentada, con su acuse.

    El acuse es lo unico que prueba que presentaste. Guardarlo suelto en una
    carpeta es como no tenerlo el dia que alguien lo pide.
    """

    class Kind(models.TextChoices):
        MONTHLY = "monthly", "Pago provisional mensual"
        ANNUAL = "annual", "Declaración anual"
        DIOT = "diot", "DIOT"
        OTHER = "other", "Otra"

    profile = models.ForeignKey(TaxProfile, verbose_name="de quién",
                               on_delete=models.CASCADE, related_name="filings")
    kind = models.CharField("qué declaración", max_length=10,
                            choices=Kind.choices, default=Kind.MONTHLY)
    period = models.CharField("periodo", max_length=7)      # AAAA o AAAA-MM
    filed_on = models.DateField("presentada el", null=True, blank=True)
    amount_paid = models.DecimalField("lo que pagaste", max_digits=16,
                                      decimal_places=2, null=True, blank=True)
    balance_favor = models.DecimalField("saldo a favor", max_digits=16,
                                        decimal_places=2, null=True, blank=True)
    receipt = models.ForeignKey(
        "core.Document", verbose_name="acuse", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="filings",
    )
    note = models.CharField("nota", max_length=300, blank=True)

    class Meta:
        ordering = ["-period"]
        verbose_name = "declaración"
        verbose_name_plural = "declaraciones"
        constraints = [
            models.UniqueConstraint(fields=["profile", "kind", "period"],
                                    name="uniq_declaracion_periodo"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.period}"

    @property
    def is_filed(self) -> bool:
        return self.filed_on is not None
