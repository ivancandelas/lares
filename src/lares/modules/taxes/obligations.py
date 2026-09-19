"""El calendario fiscal, por régimen.

Solo entran aqui las fechas que estan en la ley y no se mueven cada ano:

    pago provisional mensual   dia 17 del mes siguiente (arts. 106, 113-E,
                               116 LISR, segun el regimen)
    declaracion anual          30 de abril del ano siguiente (art. 150 LISR)

**La DIOT se quedo fuera a proposito.** Su fecha limite ha cambiado varias
veces y una fecha equivocada en un sistema de avisos es peor que no tener el
aviso: la persona confia en el y llega tarde. Mientras no se pueda fechar con
certeza por ano, se registra a mano como cualquier otra regla recurrente.
"""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec

from .models import Filing, TaxProfile

DIA_PROVISIONAL = 17
ANUAL = (4, 30)


def _ya_presentada(profile, kind, period) -> bool:
    return Filing.objects.filter(profile=profile, kind=kind, period=period,
                                 filed_on__isnull=False).exists()


class MonthlyProvisional(ObligationProvider):
    """El pago provisional de cada mes.

    Es el que de verdad se olvida: la anual la recuerda todo el mundo porque
    sale en las noticias, y los recargos de doce meses sin presentar salen de
    estos.
    """

    key = "taxes.monthly"
    label = "Pago provisional"
    applies_to = "tax_profile"

    def generate(self, profile, on_date: dt.date):
        if not (profile.is_active and profile.files_monthly):
            return []

        specs = []
        # Dos periodos: el que ya cerro y el que esta por cerrar.
        for atras in (1, 0):
            mes = on_date.month - atras
            ano = on_date.year
            if mes < 1:
                mes, ano = mes + 12, ano - 1
            periodo = f"{ano}-{mes:02d}"
            if _ya_presentada(profile, Filing.Kind.MONTHLY, periodo):
                continue
            vence_mes, vence_ano = (mes % 12 + 1), ano + (1 if mes == 12 else 0)
            vence = dt.date(vence_ano, vence_mes, DIA_PROVISIONAL)
            if vence < on_date:
                continue
            specs.append(ObligationSpec(
                dedupe_key=f"tax:{profile.pk}:monthly:{periodo}",
                title=f"Pago provisional de {periodo} · {profile.taxpayer}",
                due_on=vence,
                severity="high",
                remind_offsets=(-10, -3, -1),
                payload={"regime": profile.regime, "period": periodo},
            ))
        return specs


class AnnualReturn(ObligationProvider):
    """La declaración anual: 30 de abril del año siguiente."""

    key = "taxes.annual"
    label = "Declaración anual"
    applies_to = "tax_profile"

    def generate(self, profile, on_date: dt.date):
        if not profile.is_active:
            return []

        ejercicio = on_date.year - 1 if on_date.month <= ANUAL[0] else on_date.year
        periodo = str(ejercicio)
        if _ya_presentada(profile, Filing.Kind.ANNUAL, periodo):
            ejercicio, periodo = ejercicio + 1, str(ejercicio + 1)

        vence = dt.date(ejercicio + 1, *ANUAL)
        # Para un asalariado la anual no siempre es obligatoria; decirlo es
        # mas util que generar un aviso que quiza no le toca.
        salvedad = (" (obligatoria si tuviste dos patrones, ingresos altos u "
                    "otros supuestos)"
                    if profile.regime == TaxProfile.Regime.SALARIES else "")
        return [ObligationSpec(
            dedupe_key=f"tax:{profile.pk}:annual:{periodo}",
            title=f"Declaración anual {periodo} · {profile.taxpayer}{salvedad}",
            due_on=vence,
            severity="high",
            remind_offsets=(-90, -30, -7),
            payload={"regime": profile.regime, "period": periodo},
        )]
