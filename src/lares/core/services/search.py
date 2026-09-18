"""Busqueda global sobre todo el grafo.

Una sola barra que encuentra cualquier cosa. Basta con recorrer cuatro modelos
del nucleo porque Resource, por herencia multi-tabla, cubre lo que aporten
todos los modulos: un vehiculo o una poliza aparecen sin que la busqueda sepa
que existen.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Document, Obligation, Party, Resource
from ..scoping import use_household


@dataclass(frozen=True)
class Hit:
    kind: str
    label: str
    title: str
    subtitle: str
    url: str | None = None


def search(household, query: str, limit: int = 30) -> list[Hit]:
    query = (query or "").strip()
    if len(query) < 2:
        return []

    hits: list[Hit] = []
    with use_household(household):
        for r in Resource.objects.filter(name__icontains=query)[:limit]:
            hits.append(Hit("resource", r.kind or "recurso", r.name,
                            r.get_status_display()))
        for p in Party.objects.filter(name__icontains=query)[:limit]:
            hits.append(Hit("party", p.get_kind_display(), p.name, p.tax_id or ""))
        for d in Document.objects.filter(title__icontains=query)[:limit]:
            hits.append(Hit("document", d.doc_type or "documento", d.title,
                            f"vence {d.expires_on}" if d.expires_on else ""))
        for o in Obligation.objects.filter(title__icontains=query)[:limit]:
            hits.append(Hit("obligation", o.get_status_display(), o.title,
                            str(o.due_on)))
    return hits[:limit]
