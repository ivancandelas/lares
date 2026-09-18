from django.db import models

from lares.core.models import Resource


class Vehicle(Resource):
    """Hereda de Resource: obtiene propietario, ubicacion, valor, documentos,
    aristas del grafo y obligaciones sin declarar nada de eso."""

    resource_kind = "vehicle"

    make = models.CharField("marca", max_length=60, blank=True)
    model = models.CharField("modelo", max_length=60, blank=True)
    year = models.PositiveIntegerField("año", null=True, blank=True)

    vin = models.CharField("número de serie", max_length=24, blank=True, db_index=True)
    plates = models.CharField("placas", max_length=16, blank=True, db_index=True)
    engine_number = models.CharField("número de motor", max_length=40, blank=True)

    odometer_km = models.PositiveIntegerField("kilometraje", null=True, blank=True)
    odometer_at = models.DateField("kilometraje tomado el", null=True, blank=True)
    avg_km_per_month = models.PositiveIntegerField("kilómetros al mes", null=True, blank=True)

    service_interval_km = models.PositiveIntegerField("servicio cada (km)", null=True,
                                                      blank=True, default=10000)
    last_service_km = models.PositiveIntegerField("último servicio a los (km)",
                                                  null=True, blank=True)
    last_service_on = models.DateField("último servicio el", null=True, blank=True)

    class Meta:
        verbose_name = "vehículo"
        verbose_name_plural = "vehículos"

    def __str__(self):
        parts = [p for p in (self.make, self.model, str(self.year or "")) if p]
        return " ".join(parts) or self.name

    def context_line(self) -> str:
        partes = [
            self.plates,
            f"{self.odometer_km:,} km" if self.odometer_km else "",
            str(self.owner) if self.owner else "",
        ]
        return ", ".join(p for p in partes if p)

    @property
    def last_plate_digit(self) -> int | None:
        digits = [c for c in self.plates if c.isdigit()]
        return int(digits[-1]) if digits else None
