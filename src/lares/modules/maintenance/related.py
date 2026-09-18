"""Lo que cuelga de un proveedor: que hizo y cuanto le has pagado."""

from django.db.models import Sum
from django.urls import reverse

from lares.core.models import Party
from lares.core.registry import RelatedLink
from lares.core.related import _importe

from .models import MaintenancePlan, WorkOrder


def for_party(party) -> list:
    if not isinstance(party, Party):
        return []

    salida = []
    trabajos = WorkOrder.objects.filter(provider=party)
    n = trabajos.count()
    if n:
        total = trabajos.aggregate(t=Sum("cost"))["t"] or 0
        salida.append(RelatedLink(
            label="trabajo hecho" if n == 1 else "trabajos hechos", count=n,
            url=reverse("maintenance:providers"),
            hint=f"{_importe(total, party.household)} pagados" if total else "",
        ))

    planes = MaintenancePlan.objects.filter(preferred_provider=party,
                                            is_active=True).count()
    if planes:
        salida.append(RelatedLink(label="plan a su cargo" if planes == 1
                                  else "planes a su cargo", count=planes,
                                  url=reverse("maintenance:list")))
    return salida
