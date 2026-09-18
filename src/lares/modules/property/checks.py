"""Huecos de la cartera de inmuebles."""

from django.contrib.contenttypes.models import ContentType

from lares.core.models import Link
from lares.core.registry import Check, Finding

from .models import Property, Service


def _con_documentos(modelo) -> set:
    ctype = ContentType.objects.get_for_model(modelo)
    return set(
        Link.objects.filter(role="documents", target_type=ctype)
        .values_list("target_id", flat=True)
    )


class PropertyWithoutDeed(Check):
    key = "property.no_deed"
    label = "Inmueble sin escritura registrada"
    severity = "critical"

    def run(self, household):
        documentados = _con_documentos(Property)
        return [
            Finding(
                check=self.key,
                title=f"{p.name} no tiene escritura ni documentos",
                detail="Sin escritura no se vende, no se hereda y no se acredita como tuyo.",
                severity=self.severity,
                subject_type="property",
                subject_id=p.pk,
            )
            for p in Property.objects.filter(status=Property.Status.ACTIVE)
            if p.is_mine and p.pk not in documentados
        ]


class PropertyWithoutInsurance(Check):
    key = "property.no_insurance"
    label = "Inmueble sin seguro"
    severity = "high"

    def run(self, household):
        ctype = ContentType.objects.get_for_model(Property)
        asegurados = set(
            Link.objects.filter(role="insures", target_type=ctype)
            .values_list("target_id", flat=True)
        )
        return [
            Finding(
                check=self.key,
                title=f"{p.name} no tiene seguro registrado",
                detail="Es, casi siempre, la cosa más cara que tienes sin cubrir.",
                severity=self.severity,
                subject_type="property",
                subject_id=p.pk,
            )
            for p in Property.objects.filter(status=Property.Status.ACTIVE)
            if p.is_mine and p.property_type != Property.Type.LAND
            and p.pk not in asegurados
        ]


class RentedWithoutDeposit(Check):
    """Vivir de renta sin registrar el depósito es regalar dinero al salir."""

    key = "property.no_deposit"
    label = "Renta sin depósito registrado"
    severity = "normal"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"No registraste el depósito de {p.name}",
                detail="Sin el importe y el acta de entrega, recuperarlo depende de la memoria.",
                severity=self.severity,
                subject_type="property",
                subject_id=p.pk,
            )
            for p in Property.objects.filter(
                status=Property.Status.ACTIVE, tenure=Property.Tenure.RENTED
            )
            if not p.deposit_amount
        ]


class PropertyWithoutServices(Check):
    key = "property.no_services"
    label = "Inmueble habitado sin servicios registrados"
    severity = "low"

    def run(self, household):
        habitados = Property.objects.filter(
            status=Property.Status.ACTIVE,
            use__in=[Property.Use.LIVED_IN, Property.Use.RENTED_OUT],
        )
        con_servicios = set(
            Service.objects.values_list("property_ref_id", flat=True)
        )
        return [
            Finding(
                check=self.key,
                title=f"{p.name} no tiene servicios registrados",
                detail="Agua, luz, gas e internet generan recibos todos los meses.",
                severity=self.severity,
                subject_type="property",
                subject_id=p.pk,
            )
            for p in habitados
            if p.property_type != Property.Type.LAND and p.pk not in con_servicios
        ]
