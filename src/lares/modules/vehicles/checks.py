"""Detectores de huecos del modulo de vehiculos."""

from django.contrib.contenttypes.models import ContentType

from lares.core.models import Link
from lares.core.registry import Check, Finding

from .models import Vehicle


class VehicleWithoutPolicy(Check):
    key = "vehicles.no_policy"
    label = "Vehiculo sin poliza de seguro"
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
                title=f"{vehicle} no tiene poliza asociada",
                detail="Un vehiculo activo sin seguro registrado es el hueco mas caro posible.",
                severity=self.severity,
                subject_type="vehicle",
                subject_id=vehicle.pk,
            )
            for vehicle in Vehicle.objects.filter(status=Vehicle.Status.ACTIVE)
            if vehicle.pk not in insured_ids
        ]


class VehicleWithoutInvoice(Check):
    key = "vehicles.no_invoice"
    label = "Vehiculo sin factura registrada"
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
                detail="Sin factura no se puede vender, asegurar ni reclamar.",
                severity=self.severity,
                subject_type="vehicle",
                subject_id=vehicle.pk,
            )
            for vehicle in Vehicle.objects.filter(status=Vehicle.Status.ACTIVE)
            if vehicle.pk not in documented
        ]
