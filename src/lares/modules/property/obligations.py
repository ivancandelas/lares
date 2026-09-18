"""Lo que genera un inmueble, sea tuyo o no.

El predial se fue a packs/mx-jalisco.yaml y la renta al modulo de arrendamiento:
la renta es del contrato, no del inmueble, y funciona igual seas el inquilino o
el arrendador. Lo que se queda aqui depende de datos que solo este modulo
entiende.
"""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec
from lares.core.schedule import next_occurrences

from .models import Service

MESES_POR_CICLO = {
    Service.Cycle.MONTHLY: 1,
    Service.Cycle.BIMONTHLY: 2,
    Service.Cycle.QUARTERLY: 3,
    Service.Cycle.YEARLY: 12,
}


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
