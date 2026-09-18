"""Lo que cuelga de una aseguradora o de un agente."""

from django.urls import reverse

from lares.core.models import Party
from lares.core.registry import RelatedLink
from lares.core.related import _importe

from .models import Policy


def for_party(party) -> list:
    if not isinstance(party, Party):
        return []

    salida = []
    emitidas = Policy.objects.filter(insurer=party, status=Policy.Status.ACTIVE)
    n = emitidas.count()
    if n:
        cobertura = sum(p.coverage_amount or 0 for p in emitidas)
        salida.append(RelatedLink(
            label="póliza" if n == 1 else "pólizas", count=n,
            url=reverse("insurance:list"),
            hint=f"{_importe(cobertura, party.household)} asegurados" if cobertura else "",
        ))

    corretaje = Policy.objects.filter(agent=party).count()
    if corretaje:
        salida.append(RelatedLink(label="pólizas como agente", count=corretaje,
                                  url=reverse("insurance:list")))
    return salida
