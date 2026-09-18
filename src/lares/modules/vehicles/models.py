from django.db import models

from lares.core.models import Resource


class Vehicle(Resource):
    """Hereda de Resource: obtiene propietario, ubicacion, valor, documentos,
    aristas del grafo y obligaciones sin declarar nada de eso."""

    resource_kind = "vehicle"

    make = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=60, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)

    vin = models.CharField(max_length=24, blank=True, db_index=True)
    plates = models.CharField(max_length=16, blank=True, db_index=True)
    engine_number = models.CharField(max_length=40, blank=True)

    odometer_km = models.PositiveIntegerField(null=True, blank=True)
    odometer_at = models.DateField(null=True, blank=True)
    avg_km_per_month = models.PositiveIntegerField(null=True, blank=True)

    service_interval_km = models.PositiveIntegerField(null=True, blank=True, default=10000)
    last_service_km = models.PositiveIntegerField(null=True, blank=True)
    last_service_on = models.DateField(null=True, blank=True)

    def __str__(self):
        parts = [p for p in (self.make, self.model, str(self.year or "")) if p]
        return " ".join(parts) or self.name

    @property
    def last_plate_digit(self) -> int | None:
        digits = [c for c in self.plates if c.isdigit()]
        return int(digits[-1]) if digits else None
