from lares.core.forms import ResourceForm

from .models import Property, Service


class PropertyForm(ResourceForm):
    GROUPS = (
        ("Qué es y cómo lo tienes", ["name", "property_type", "tenure", "use"]),
        ("Dónde está", ["address", "city", "subdivision", "land_m2", "built_m2"]),
        ("Solo si es tuyo", ["owner", "acquired_on", "purchase_amount",
                             "current_value", "currency", "cadastral_id",
                             "deed_number", "deed_date", "ownership_share",
                             "predial_month", "predial_amount"]),
        ("Solo si vives de renta", ["landlord", "rent_amount", "rent_due_day",
                                    "deposit_amount", "lease_ends_on"]),
        ("Notas", ["status", "description"]),
    )

    class Meta:
        model = Property
        fields = ["name", "property_type", "tenure", "use", "address", "city",
                  "subdivision", "land_m2", "built_m2", "owner", "acquired_on",
                  "purchase_amount", "current_value", "currency",
                  "cadastral_id", "deed_number", "deed_date", "ownership_share",
                  "predial_month", "predial_amount",
                  "landlord", "rent_amount", "rent_due_day", "deposit_amount",
                  "lease_ends_on", "status", "description"]
        labels = {
            "name": "Cómo lo llamas",
            "property_type": "Qué es",
            "tenure": "Tu relación con él",
            "use": "Qué se hace con él",
            "address": "Dirección",
            "city": "Ciudad",
            "subdivision": "Estado",
            "land_m2": "Terreno (m²)",
            "built_m2": "Construcción (m²)",
            "owner": "A nombre de",
            "acquired_on": "Desde cuándo",
            "purchase_amount": "Lo que costó",
            "current_value": "Lo que vale hoy",
            "currency": "Moneda",
            "cadastral_id": "Clave catastral",
            "deed_number": "Escritura",
            "deed_date": "Fecha de escritura",
            "ownership_share": "Tu parte (%)",
            "predial_month": "Mes del predial",
            "predial_amount": "Predial estimado",
            "landlord": "Arrendador",
            "rent_amount": "Renta que pagas",
            "rent_due_day": "Día de pago",
            "deposit_amount": "Depósito en garantía",
            "lease_ends_on": "El contrato acaba el",
            "status": "Estado",
            "description": "Notas",
        }
        help_texts = {
            "tenure": "«Rentado» es cuando tú eres el inquilino. No suma a tu patrimonio.",
            "use": "Independiente de lo anterior: puedes rentar algo que es tuyo.",
            "ownership_share": "Solo si es en copropiedad.",
            "rent_amount": "Se convierte en un pago mensual que te recuerda solo.",
            "lease_ends_on": "Avisa con 90 días: renovar o mudarse no se decide en una semana.",
        }


class ServiceForm(ResourceForm):
    GROUPS = (
        ("Qué servicio", ["name", "service_kind", "property_ref", "provider",
                          "contract_number"]),
        ("Cuándo y cuánto", ["cycle", "due_day", "typical_amount", "currency",
                             "status"]),
    )

    class Meta:
        model = Service
        fields = ["name", "service_kind", "property_ref", "provider",
                  "contract_number", "cycle", "due_day", "typical_amount",
                  "currency", "status"]
        labels = {
            "name": "Cómo lo llamas",
            "service_kind": "Qué servicio",
            "property_ref": "De qué inmueble",
            "provider": "Proveedor",
            "contract_number": "Número de contrato",
            "cycle": "Cada cuánto llega",
            "due_day": "Día de pago",
            "typical_amount": "Lo que suele costar",
            "currency": "Moneda",
            "status": "Estado",
        }
        help_texts = {
            "due_day": "Con esto el recibo aparece solo cada periodo.",
            "contract_number": "El número que viene en el recibo.",
        }
