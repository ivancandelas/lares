from lares.core.forms import ResourceForm

from .models import Vehicle


class VehicleForm(ResourceForm):
    # Con placas y dueño ya se puede generar el refrendo y la
    # verificación, que es para lo que se registra un coche.
    ESENCIALES = ("name", "plates", "owner")

    GROUPS = (
        ("Qué coche es", ["name", "make", "model", "year", "plates", "vin"]),
        ("De quién y dónde", ["owner", "location", "acquired_on"]),
        ("Uso y mantenimiento", ["odometer_km", "avg_km_per_month",
                                 "service_interval_km", "last_service_km",
                                 "last_service_on"]),
        ("Cuánto vale", ["purchase_amount", "current_value", "currency", "status"]),
    )

    class Meta:
        model = Vehicle
        fields = [
            "name", "make", "model", "year", "plates", "vin",
            "owner", "location", "odometer_km", "avg_km_per_month",
            "service_interval_km", "last_service_km", "last_service_on",
            "acquired_on", "purchase_amount", "current_value", "currency", "status",
        ]
        labels = {
            "name": "Cómo lo llamas",
            "make": "Marca",
            "model": "Modelo",
            "year": "Año",
            "plates": "Placas",
            "vin": "Número de serie (VIN)",
            "owner": "De quién es",
            "location": "Dónde se guarda",
            "odometer_km": "Kilometraje actual",
            "avg_km_per_month": "Kilómetros al mes",
            "service_interval_km": "Servicio cada (km)",
            "last_service_km": "Último servicio a los (km)",
            "last_service_on": "Fecha del último servicio",
            "acquired_on": "Desde cuándo lo tienes",
            "purchase_amount": "Lo que costó",
            "current_value": "Lo que vale hoy",
            "currency": "Moneda",
            "status": "Estado",
        }
        help_texts = {
            "plates": "De aquí sale el calendario de verificación.",
            "odometer_km": "Con esto se estima cuándo toca el próximo servicio.",
        }
