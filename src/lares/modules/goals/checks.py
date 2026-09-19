"""Lo que una meta necesita que alguien le diga.

Una meta no genera vencimientos: nadie te multa por no ahorrar. Lo que si hace
falta es que el sistema avise cuando la aritmetica ya no cuadra, que es
justamente lo que uno deja de mirar.
"""

import datetime as dt
from decimal import Decimal

from lares.core.registry import Check, Finding

from .models import Goal

SIN_MOVER = 3        # meses de silencio antes de decir algo


class Behind(Check):
    """«A este ritmo llegarías siete meses tarde».

    Es la frase que convierte una barra de progreso en una decision: o subes la
    aportacion, o mueves la fecha, o cambias la meta. Callarlo hasta el final
    deja las tres opciones fuera de tiempo.
    """

    key = "goals.behind"
    label = "Meta que no llega a tiempo"
    severity = "normal"

    def run(self, household):
        hallazgos = []
        for meta in Goal.objects.filter(is_active=True, target_on__isnull=False):
            if meta.is_reached:
                continue
            tarde = meta.months_late
            if tarde is None or tarde <= 0:
                continue
            falta = meta.gap
            detalle = (f"Llegarías en {meta.eta:%m/%Y} y la querías para "
                       f"{meta.target_on:%m/%Y}.")
            if falta:
                detalle += (f" Te faltan {falta:,.0f} al mes para llegar a "
                            f"tiempo.")
            hallazgos.append(Finding(
                check=self.key,
                title=f"{meta.name}: a este ritmo llegarías {tarde} "
                      f"{'mes' if tarde == 1 else 'meses'} tarde",
                detail=detalle,
                severity="high" if tarde > 6 else self.severity,
                subject_type="goal", subject_id=meta.pk,
            ))
        return hallazgos


class NoPace(Check):
    """Una meta con fecha y sin un solo peso apartado todavía."""

    key = "goals.no_pace"
    label = "Meta sin arrancar"
    severity = "normal"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{meta.name} no ha arrancado",
                detail=(f"Harían falta {meta.monthly_needed:,.0f} al mes para "
                        f"llegar a {meta.target_on:%m/%Y}."
                        if meta.monthly_needed else
                        "Sin una sola aportación no hay ritmo que proyectar."),
                severity=self.severity,
                subject_type="goal", subject_id=meta.pk,
            )
            for meta in Goal.objects.filter(is_active=True, kind=Goal.Kind.SAVE)
            if not meta.is_reached and meta.months_elapsed >= 1
            and not meta.contributions.exists()
        ]


class Stalled(Check):
    """Meses sin mover una meta que sigue abierta.

    No es un regano: casi siempre significa que la meta ya no importa y lo que
    toca es cerrarla, para que deje de competir por dinero que va a otra parte.
    """

    key = "goals.stalled"
    label = "Meta parada"
    severity = "low"

    def run(self, household):
        hoy = dt.date.today()
        hallazgos = []
        for meta in Goal.objects.filter(is_active=True, kind=Goal.Kind.SAVE):
            ultima = meta.last_movement
            if meta.is_reached or not ultima:
                continue
            meses = (hoy.year - ultima.year) * 12 + (hoy.month - ultima.month)
            if meses < SIN_MOVER:
                continue
            hallazgos.append(Finding(
                check=self.key,
                title=f"{meta.name} lleva {meses} meses sin moverse",
                detail=(f"La última aportación fue el {ultima:%d/%m/%Y}. Si ya "
                        f"no la quieres, ciérrala y libera el dinero."),
                severity=self.severity,
                subject_type="goal", subject_id=meta.pk,
            ))
        return hallazgos


class Reached(Check):
    """Llegaste. Cerrarla es lo que deja sitio a la siguiente."""

    key = "goals.reached"
    label = "Meta cumplida"
    severity = "low"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{meta.name}: llegaste",
                detail=(f"{meta.current:,.0f} de {meta.target_amount:,.0f}. "
                        f"Ciérrala para que el dinero deje de estar apartado."
                        if not meta.is_payoff else
                        f"Ya no debes nada de {meta.name}. Ciérrala."),
                severity=self.severity,
                subject_type="goal", subject_id=meta.pk,
            )
            for meta in Goal.objects.filter(is_active=True)
            if meta.is_reached
        ]


class DebtGrowing(Check):
    """Una meta de saldar en la que la deuda creció en vez de bajar.

    Es el unico caso en el que la barra de progreso se mueve hacia atras, y el
    que mas conviene ver pronto.
    """

    key = "goals.debt_growing"
    label = "Deuda que crece"
    severity = "high"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{meta.name}: debes más que cuando empezaste",
                detail=(f"Empezaste debiendo {meta.baseline_amount:,.0f} y hoy "
                        f"debes {meta.current:,.0f}. Abonar no alcanza si se "
                        f"sigue cargando."),
                severity=self.severity,
                subject_type="goal", subject_id=meta.pk,
            )
            for meta in Goal.objects.filter(is_active=True,
                                            kind=Goal.Kind.PAYOFF)
            if meta.account and meta.current > meta.baseline_amount > Decimal(0)
        ]
