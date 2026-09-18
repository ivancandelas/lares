import datetime as dt

from lares.core.registry import Check, Finding

from .models import MaintenancePlan, WorkOrder


class OverdueMaintenance(Check):
    key = "maintenance.overdue"
    label = "Mantenimiento muy atrasado"
    severity = "high"

    # Más del doble del periodo sin hacerlo ya no es un retraso, es un olvido.
    FACTOR = 2

    def run(self, household):
        hoy = dt.date.today()
        hallazgos = []
        for plan in MaintenancePlan.objects.filter(is_active=True):
            if plan.basis != MaintenancePlan.Basis.TIME or not plan.every_months:
                continue
            if not plan.last_done_on:
                continue
            meses = (hoy.year - plan.last_done_on.year) * 12 + \
                    (hoy.month - plan.last_done_on.month)
            if meses >= plan.every_months * self.FACTOR:
                hallazgos.append(Finding(
                    check=self.key,
                    title=f"{plan.title} de {plan.subject} lleva {meses} meses sin hacerse",
                    detail=f"Toca {plan.cadence}. La última vez fue el "
                           f"{plan.last_done_on:%d/%m/%Y}.",
                    severity=self.severity,
                ))
        return hallazgos


class WorkWithoutProvider(Check):
    key = "maintenance.no_provider"
    label = "Trabajo sin saber quién lo hizo"
    severity = "low"

    def run(self, household):
        sin_dueno = WorkOrder.objects.filter(provider__isnull=True)
        if not sin_dueno:
            return []
        return [Finding(
            check=self.key,
            title=f"{len(sin_dueno)} trabajo(s) sin registrar quién los hizo",
            detail="Si vuelve a fallar, no sabrás a quién llamar ni si hay garantía.",
            severity=self.severity,
        )]
