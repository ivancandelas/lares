"""Detectores de huecos del modulo de vehiculos."""

from django.contrib.contenttypes.models import ContentType

from lares.core.models import Link
from lares.core.registry import Check, Finding

from .models import Vehicle


class VehicleWithoutPolicy(Check):
    key = "vehicles.no_policy"
    label = "Vehículo sin póliza de seguro"
    severity = "critical"

    def run(self, household):
        ctype = ContentType.objects.get_for_model(Vehicle)
        insured_ids = set(
            Link.objects.filter(role="insures", target_type=ctype)
            .values_list("target_id", flat=True)
        )
        return [
            Finding(
                check=self.key,
                title=f"{vehicle} no tiene póliza asociada",
                detail="Un vehículo activo sin seguro es el hueco más caro que puedes tener.",
                severity=self.severity,
                subject_type="vehicle",
                subject_id=vehicle.pk,
            )
            for vehicle in Vehicle.objects.filter(status=Vehicle.Status.ACTIVE)
            if vehicle.pk not in insured_ids
        ]


class VehicleWithoutInvoice(Check):
    key = "vehicles.no_invoice"
    label = "Vehículo sin factura registrada"
    severity = "normal"

    def run(self, household):
        ctype = ContentType.objects.get_for_model(Vehicle)
        documented = set(
            Link.objects.filter(role="documents", target_type=ctype)
            .values_list("target_id", flat=True)
        )
        return [
            Finding(
                check=self.key,
                title=f"{vehicle} no tiene factura ni documentos",
                detail="Sin factura no lo puedes vender, asegurar ni reclamar.",
                severity=self.severity,
                subject_type="vehicle",
                subject_id=vehicle.pk,
            )
            for vehicle in Vehicle.objects.filter(status=Vehicle.Status.ACTIVE)
            if vehicle.pk not in documented
        ]
