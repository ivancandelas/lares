"""Huecos de cobertura."""

import datetime as dt
from decimal import Decimal

from lares.core.registry import Check, Finding

from .models import Policy


class ExpiredPolicy(Check):
    key = "insurance.expired"
    label = "Póliza vencida"
    severity = "critical"

    def run(self, household):
        hoy = dt.date.today()
        return [
            Finding(
                check=self.key,
                title=f"{p.name} venció el {p.ends_on:%d/%m/%Y}",
                detail="Mientras no se renueve, lo que cubría está sin cobertura.",
                severity=self.severity,
                subject_type="policy",
                subject_id=p.pk,
            )
            for p in Policy.objects.filter(status=Policy.Status.ACTIVE,
                                           ends_on__lt=hoy)
        ]


class PolicyCoversNothing(Check):
    key = "insurance.covers_nothing"
    label = "Póliza que no cubre nada"
    severity = "normal"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{p.name} no está asociada a nada",
                detail="Sin saber qué cubre, no sirve para reclamar ni para comparar.",
                severity=self.severity,
                subject_type="policy",
                subject_id=p.pk,
            )
            for p in Policy.objects.filter(status=Policy.Status.ACTIVE)
            if not p.insured_resources().exists()
        ]


class Underinsured(Check):
    """La suma asegurada se queda corta y nadie se entera hasta el siniestro."""

    key = "insurance.underinsured"
    label = "Suma asegurada por debajo del valor"
    severity = "high"

    # Decimal, no float: mezclarlos revienta al multiplicar importes.
    MARGEN = Decimal("0.8")

    def run(self, household):
        hallazgos = []
        for policy in Policy.objects.filter(status=Policy.Status.ACTIVE):
            if not policy.coverage_amount:
                continue
            for recurso in policy.insured_resources():
                valor = recurso.current_value or recurso.purchase_amount
                if valor and policy.coverage_amount < valor * self.MARGEN:
                    hallazgos.append(Finding(
                        check=self.key,
                        title=f"{recurso.name} vale más de lo que cubre su póliza",
                        detail=(f"Asegurado por {policy.coverage_amount:,.0f} "
                                f"y registrado en {valor:,.0f}."),
                        severity=self.severity,
                        subject_type="policy",
                        subject_id=policy.pk,
                    ))
        return hallazgos
