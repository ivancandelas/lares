"""Lo que se puede calcular sin meterse a declarar.

La linea esta puesta a proposito donde la aritmetica deja de ser auditable:

  - **La base gravable se calcula.** Ingresos menos deducciones es una resta, y
    cualquiera puede comprobar de donde sale cada sumando.
  - **El ISR con tarifa progresiva no se calcula.** Sus tablas cambian cada ano
    y un error se traduce en pagar de menos, que tiene consecuencias legales.
    Ese calculo es del SAT o del contador, que es de quien debe ser.
  - **RESICO es la excepcion**, porque su tasa es fija por tramo de ingreso
    mensual (art. 113-E LISR) y no ha cambiado desde que existe el regimen.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Sum

from lares.core.models import Account, Posting
from lares.core.scoping import use_household

from .models import Deduction, TaxProfile, Withholding

CENTAVO = Decimal("0.01")

# Art. 113-E LISR: tasa sobre los ingresos del mes, sin deducciones.
# (tope mensual de ingresos, tasa)
RESICO_TRAMOS = [
    (Decimal("25000"), Decimal("0.0100")),
    (Decimal("50000"), Decimal("0.0110")),
    (Decimal("83333.33"), Decimal("0.0150")),
    (Decimal("208333.33"), Decimal("0.0200")),
    (Decimal("291666.67"), Decimal("0.0250")),
]

TOPE_PERSONAL = Decimal("0.15")        # 15% de los ingresos del ejercicio


def resico_rate(ingreso_mensual: Decimal) -> Decimal | None:
    """La tasa del mes. None si el ingreso se sale de la tabla.

    Pasado el ultimo tramo ya no aplica RESICO, y devolver la tasa mas alta
    disimularia justamente el hecho de que hay que cambiar de regimen.
    """
    for tope, tasa in RESICO_TRAMOS:
        if ingreso_mensual <= tope:
            return tasa
    return None


@dataclass
class Cap:
    """Un tope de deducción: cuál es, de dónde sale y si ya lo alcanzaste."""

    label: str
    limit: Decimal | None
    applied: bool = True
    note: str = ""


@dataclass
class Summary:
    profile: object
    year: int
    income: Decimal = Decimal(0)
    blind_deduction: Decimal = Decimal(0)
    personal: Decimal = Decimal(0)
    personal_allowed: Decimal = Decimal(0)
    business: Decimal = Decimal(0)
    withheld_isr: Decimal = Decimal(0)
    withheld_iva: Decimal = Decimal(0)
    by_kind: dict = field(default_factory=dict)
    caps: list = field(default_factory=list)

    @property
    def deductions(self) -> Decimal:
        return self.blind_deduction + self.personal_allowed + self.business

    @property
    def other_deductions(self) -> Decimal:
        """Lo deducible que sí requiere comprobante, sin la ciega."""
        return self.personal_allowed + self.business

    @property
    def base(self) -> Decimal:
        """Sobre lo que se declara. No es el impuesto."""
        return max(self.income - self.deductions, Decimal(0))

    @property
    def over_cap(self) -> Decimal:
        """Lo que dedujiste de más y no va a contar."""
        return max(self.personal - self.personal_allowed, Decimal(0))

    @property
    def resico_estimate(self) -> Decimal | None:
        """Solo para RESICO: tasa fija sobre ingresos, sin deducciones."""
        if self.profile.regime != TaxProfile.Regime.RESICO or not self.income:
            return None
        tasa = resico_rate((self.income / 12).quantize(CENTAVO))
        if tasa is None:
            return None
        return (self.income * tasa).quantize(CENTAVO)


def income_of(household, profile, year: int) -> Decimal:
    """Los ingresos del ejercicio, según el libro.

    Sale de las cuentas de ingreso y no de las facturas: una factura emitida
    que nadie pago no es un ingreso cobrado, y en persona fisica se declara lo
    cobrado.
    """
    desde, hasta = dt.date(year, 1, 1), dt.date(year, 12, 31)
    total = Posting.objects.filter(
        account__type=Account.Type.INCOME,
        entry__date__gte=desde, entry__date__lte=hasta,
    ).aggregate(t=Sum("amount"))["t"] or Decimal(0)
    # Los ingresos viven en negativo en partida doble.
    return abs(Decimal(total))


def summarize(household, profile, year: int) -> Summary:
    with use_household(household):
        resumen = Summary(profile=profile, year=year,
                          income=income_of(household, profile, year))

        deducciones = Deduction.objects.filter(
            profile=profile, date__year=year
        ).select_related("document")
        for deduccion in deducciones:
            clave = deduccion.get_kind_display()
            resumen.by_kind[clave] = (resumen.by_kind.get(clave, Decimal(0))
                                      + deduccion.amount)
            if deduccion.is_personal:
                resumen.personal += deduccion.amount
            else:
                resumen.business += deduccion.amount

        retenciones = Withholding.objects.filter(profile=profile, date__year=year)
        for retencion in retenciones:
            if retencion.kind == Withholding.Kind.ISR:
                resumen.withheld_isr += retencion.amount
            else:
                resumen.withheld_iva += retencion.amount

        ciega = profile.blind_deduction
        if ciega:
            resumen.blind_deduction = (resumen.income * ciega).quantize(CENTAVO)

        resumen.personal_allowed, resumen.caps = _apply_caps(profile, resumen)
    return resumen


def _apply_caps(profile, resumen) -> tuple:
    """El tope de las deducciones personales, con lo que se sepa.

    Es el menor entre el 15% de los ingresos y cinco UMA anuales. El primero
    es una formula; el segundo es un numero que cambia cada ano, asi que solo
    se aplica si la persona lo capturo. Callar que ese tope existe seria peor
    que no aplicarlo.
    """
    topes = []
    limites = []

    if resumen.income:
        quince = (resumen.income * TOPE_PERSONAL).quantize(CENTAVO)
        limites.append(quince)
        topes.append(Cap("15% de tus ingresos", quince))

    if profile.uma_annual:
        cinco = (profile.uma_annual * 5).quantize(CENTAVO)
        limites.append(cinco)
        topes.append(Cap("5 UMA anuales", cinco))
    else:
        topes.append(Cap(
            "5 UMA anuales", None, applied=False,
            note="Falta el valor de la UMA del ejercicio, así que este tope "
                 "no se aplicó. El total real puede ser menor.",
        ))

    if not limites:
        return resumen.personal, topes
    return min(resumen.personal, min(limites)), topes


def profiles(household) -> list:
    with use_household(household):
        return list(TaxProfile.objects.filter(is_active=True)
                    .select_related("taxpayer"))
