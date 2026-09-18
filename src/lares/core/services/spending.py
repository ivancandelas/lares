"""En que se va el dinero.

Tres preguntas distintas que la gente hace de verdad, y que necesitan tres ejes
distintos del mismo apunte:

    "cuanto llevo gastado en Walmart"        -> el comercio  (Entry.counterparty)
    "cuanto le he dado a mi hijo"            -> la persona   (Posting.beneficiary)
    "cuanto se va en gasolina y mascotas"    -> la categoria (Account)
    "cuanto me cuesta el Mazda"              -> la cosa      (Posting.dimension)

Confundirlos es lo que hace inservibles a casi todas las apps de finanzas
personales: meten todo en "categoria" y luego no se puede responder ninguna.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from django.db.models import Count, Sum

from ..models import Account, Posting
from ..scoping import use_household

PERIODOS = {
    "month": ("Este mes", 30),
    "quarter": ("Últimos 3 meses", 90),
    "year": ("Último año", 365),
    "all": ("Todo", None),
}


@dataclass(frozen=True)
class Row:
    label: str
    total: object
    count: int
    share: float = 0.0
    key: object = None          # id de la parte o la cosa, para poder enlazar
    url: str = ""


def _gastos(desde: dt.date | None):
    qs = Posting.objects.filter(account__type=Account.Type.EXPENSE, amount__gt=0)
    return qs.filter(entry__date__gte=desde) if desde else qs


def _ingresos(desde: dt.date | None):
    """En partida doble un ingreso vive en negativo; se muestra en positivo.

    Nadie dice "gané menos cuarenta y dos mil".
    """
    qs = Posting.objects.filter(account__type=Account.Type.INCOME, amount__lt=0)
    return qs.filter(entry__date__gte=desde) if desde else qs


def _rows(qs, campo: str, etiqueta_vacia: str, campo_id: str | None = None,
          negativo: bool = False) -> list[Row]:
    campos = [campo] + ([campo_id] if campo_id else [])
    datos = (
        qs.values(*campos)
        .annotate(total=Sum("amount"), n=Count("id"))
        .order_by("total" if negativo else "-total")
    )
    filas = [
        Row(label=d[campo] or etiqueta_vacia,
            total=-d["total"] if negativo else d["total"], count=d["n"],
            key=d.get(campo_id) if campo_id else None)
        for d in datos if d["total"]
    ]
    suma = sum(f.total for f in filas) or 1
    return [
        Row(f.label, f.total, f.count, share=float(f.total) / float(suma), key=f.key)
        for f in filas
    ]


def report(household, periodo: str = "quarter") -> dict:
    etiqueta, dias = PERIODOS.get(periodo, PERIODOS["quarter"])
    desde = dt.date.today() - dt.timedelta(days=dias) if dias else None

    with use_household(household):
        qs = _gastos(desde)
        total = qs.aggregate(t=Sum("amount"))["t"] or 0

        entradas = _ingresos(desde)
        total_entra = -(entradas.aggregate(t=Sum("amount"))["t"] or 0)

        return {
            "period": periodo,
            "period_label": etiqueta,
            "periods": [(k, v[0]) for k, v in PERIODOS.items()],
            "total": total,
            "total_in": total_entra,
            "balance": total_entra - total,
            "in_by_category": _rows(entradas, "account__name", "Sin clasificar",
                                    negativo=True),
            "in_by_source": _linked(
                _rows(entradas, "entry__counterparty__name", "Sin registrar",
                      "entry__counterparty_id", negativo=True)
            ),
            "by_category": _rows(qs, "account__name", "Sin categoría"),
            "by_merchant": _linked(
                _rows(qs, "entry__counterparty__name", "Sin registrar",
                      "entry__counterparty_id")
            ),
            "by_person": _rows(qs, "beneficiary__name", "Del hogar"),
            "by_thing": _things(qs),
        }


def merchant_detail(household, party, periodo: str = "year") -> dict:
    """«¿Y qué compro exactamente en Walmart?»"""
    _, dias = PERIODOS.get(periodo, PERIODOS["year"])
    desde = dt.date.today() - dt.timedelta(days=dias) if dias else None

    with use_household(household):
        qs = _gastos(desde).filter(entry__counterparty=party)
        return {
            "party": party,
            "total": qs.aggregate(t=Sum("amount"))["t"] or 0,
            "by_category": _rows(qs, "account__name", "Sin categoría"),
            "entries": qs.select_related("entry", "account").order_by("-entry__date")[:30],
        }


def _things(qs) -> list[Row]:
    """Agrupado por la cosa a la que se atribuyo el gasto.

    Se resuelve el nombre en Python porque la dimension es polimorfica: son
    pocas filas y no compensa complicar la consulta.
    """
    from ..models import Resource

    datos = (
        qs.exclude(dimension_id=None)
        .values("dimension_id")
        .annotate(total=Sum("amount"), n=Count("id"))
        .order_by("-total")
    )
    nombres = dict(
        Resource.objects.filter(
            pk__in=[d["dimension_id"] for d in datos]
        ).values_list("pk", "name")
    )
    filas = [
        Row(label=nombres.get(d["dimension_id"], "—"), total=d["total"], count=d["n"])
        for d in datos
    ]
    suma = sum(f.total for f in filas) or 1
    return [Row(f.label, f.total, f.count, float(f.total) / float(suma)) for f in filas]


def _linked(filas: list[Row]) -> list[Row]:
    """Cada comercio enlaza a su detalle: «¿y que compro exactamente ahi?»."""
    from django.urls import reverse

    salida = []
    for f in filas:
        url = reverse("finance:merchant", args=[f.key]) if f.key else ""
        salida.append(Row(f.label, f.total, f.count, f.share, f.key, url))
    return salida
