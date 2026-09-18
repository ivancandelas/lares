from lares.core.forms import ResourceForm

from .models import Belonging


class BelongingForm(ResourceForm):
    GROUPS = (
        ("Qué es", ["name", "category", "brand", "model_name", "serial_number"]),
        ("De quién y dónde", ["owner", "location", "acquired_on"]),
        ("Cuánto vale", ["purchase_amount", "current_value", "appraised_value",
                         "appraised_on", "currency"]),
        ("Garantía", ["warranty_until", "warranty_note"]),
        ("Notas", ["status", "description"]),
    )

    class Meta:
        model = Belonging
        fields = ["name", "category", "brand", "model_name", "serial_number",
                  "owner", "location", "acquired_on", "purchase_amount",
                  "current_value", "appraised_value", "appraised_on",
                  "warranty_until", "warranty_note", "currency", "status",
                  "description"]
        labels = {
            "name": "Qué es",
            "category": "Categoría",
            "brand": "Marca",
            "model_name": "Modelo",
            "serial_number": "Número de serie",
            "owner": "De quién es",
            "location": "Dónde está",
            "acquired_on": "Desde cuándo lo tienes",
            "purchase_amount": "Lo que costó",
            "current_value": "Lo que vale hoy",
            "appraised_value": "Valor de avalúo",
            "appraised_on": "Fecha del avalúo",
            "warranty_until": "Garantía hasta",
            "warranty_note": "Qué cubre la garantía",
            "currency": "Moneda",
            "status": "Estado",
            "description": "Notas",
        }
        help_texts = {
            "serial_number": "Es lo primero que pide un seguro y la policía.",
            "warranty_until": "Si la pones, el aviso se crea solo con 60 días de margen.",
            "appraised_value": "Para joyas, instrumentos y arte: es lo que cubre la póliza.",
        }
