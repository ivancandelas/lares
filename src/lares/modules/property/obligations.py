"""Lo que genera un inmueble, sea tuyo o no.

El predial se fue a packs/mx-jalisco.yaml: cambia de fecha y de importe segun el
municipio, y no necesita mas que saber si el inmueble es tuyo. Lo que se queda
aqui depende de datos que solo este modulo entiende.
"""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec
from lares.core.schedule import next_occurrences

from .models import Property, Service

MESES_POR_CICLO = {
    Service.Cycle.MONTHLY: 1,
    Service.Cycle.BIMONTHLY: 2,
    Service.Cycle.QUARTERLY: 3,
    Service.Cycle.YEARLY: 12,
}


class LeaseProvider(ObligationProvider):
    """Si vives de renta, pagar es tan obligación como cobrar lo es para otro."""

    key = "property.rent"
    label = "Renta que pagas"
    applies_to = "property"

    def generate(self, prop, on_date: dt.date):
        if prop.tenure != Property.Tenure.RENTED or not prop.rent_due_day:
            return []

        specs = [
            ObligationSpec(
                dedupe_key=f"property:{prop.pk}:rent:{due:%Y-%m}",
                title=f"Renta de {prop.name}",
                due_on=due,
                amount=prop.rent_amount,
                currency=prop.currency or None,
                counterparty=prop.landlord,
                severity="critical",
                remind_offsets=(-5, -2),
            )
            for due in next_occurrences(
                {"monthly": {"day": prop.rent_due_day}}, on_date, count=2
            )
        ]
        if prop.lease_ends_on and prop.lease_ends_on >= on_date:
            specs.append(ObligationSpec(
                dedupe_key=f"property:{prop.pk}:lease_end:{prop.lease_ends_on:%Y-%m-%d}",
                title=f"Acaba el contrato de {prop.name}",
                due_on=prop.lease_ends_on,
                severity="high",
                # Renovar o mudarse no se decide en una semana.
                remind_offsets=(-90, -60, -30, -15),
            ))
        return specs


class ServiceBillProvider(ObligationProvider):
    """Agua, luz, gas: lo paga quien vive ahí, sea dueño o inquilino."""

    key = "property.service"
    label = "Recibo de servicio"
    applies_to = "service"

    def generate(self, service, on_date: dt.date):
        if not service.due_day:
            return []
        meses = MESES_POR_CICLO.get(service.cycle, 1)
        if meses == 1:
            calendario = {"monthly": {"day": service.due_day}}
        else:
            inicio = on_date.replace(day=min(service.due_day, 28))
            calendario = {"every": {"months": meses}, "from": inicio.isoformat()}

        return [
            ObligationSpec(
                dedupe_key=f"service:{service.pk}:bill:{due:%Y-%m}",
                title=f"{service.get_service_kind_display()} de {service.property_ref.name}",
                due_on=due,
                amount=service.typical_amount,
                currency=service.currency or None,
                counterparty=service.provider,
                severity="normal",
                remind_offsets=(-5, -1),
            )
            for due in next_occurrences(calendario, on_date, count=2)
        ]
