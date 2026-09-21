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


# ---------------------------------------------------------------------------
# Estado de resultados
# ---------------------------------------------------------------------------
#
# El informe de arriba mira ventanas moviles ("ultimos 90 dias"), que sirven
# para ver en que se va el dinero pero no se pueden comparar contra nada: no
# existe "los 90 dias anteriores a los ultimos 90 dias" en la cabeza de nadie.
#
# Un estado de resultados necesita lo contrario: periodos cerrados -un mes, un
# ano- y el mismo periodo anterior al lado. Sin la comparacion es una lista de
# numeros; con ella es la unica pregunta que importa, que es si vas mejor o
# peor que antes.
#
# Los traspasos no aparecen, y no hay que filtrarlos: mover dinero entre
# cuentas propias no toca ninguna cuenta de ingreso ni de gasto. Es la ventaja
# de llevar partida doble en vez de una tabla de movimientos.


@dataclass(frozen=True)
class StatementLine:
    label: str
    amount: object
    previous: object

    @property
    def change(self):
        return self.amount - self.previous

    @property
    def change_pct(self) -> float | None:
        if not self.previous:
            return None
        return float(self.change / self.previous)

    @property
    def is_new(self) -> bool:
        """No estaba antes: conviene mirarlo aunque sea pequeño."""
        return not self.previous and bool(self.amount)


@dataclass(frozen=True)
class Statement:
    label: str
    starts_on: dt.date
    ends_on: dt.date
    income: list
    expenses: list
    previous_label: str

    @property
    def total_income(self):
        return sum((x.amount for x in self.income), 0)

    @property
    def total_expense(self):
        return sum((x.amount for x in self.expenses), 0)

    @property
    def previous_income(self):
        return sum((x.previous for x in self.income), 0)

    @property
    def previous_expense(self):
        return sum((x.previous for x in self.expenses), 0)

    @property
    def result(self):
        """Lo que quedó. Positivo es superávit; negativo, déficit."""
        return self.total_income - self.total_expense

    @property
    def previous_result(self):
        return self.previous_income - self.previous_expense

    @property
    def savings_rate(self) -> float | None:
        """Qué parte de lo que entró no se fue. Es la cifra que resume el mes."""
        if not self.total_income:
            return None
        return float(self.result / self.total_income)

    @property
    def is_partial(self) -> bool:
        """El periodo no ha terminado: comparar de igual a igual engaña."""
        return self.ends_on >= dt.date.today()


def _periodo(year: int, month: int | None) -> tuple:
    import calendar

    if month:
        ultimo = calendar.monthrange(year, month)[1]
        return dt.date(year, month, 1), dt.date(year, month, ultimo)
    return dt.date(year, 1, 1), dt.date(year, 12, 31)


def _anterior(year: int, month: int | None) -> tuple:
    if not month:
        return year - 1, None
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _por_categoria(tipo, desde: dt.date, hasta: dt.date) -> dict:
    signo = -1 if tipo == Account.Type.INCOME else 1
    filas = (
        Posting.objects.filter(account__type=tipo, entry__date__gte=desde,
                               entry__date__lte=hasta)
        .values("account__name").annotate(t=Sum("amount"))
    )
    return {f["account__name"]: signo * (f["t"] or 0) for f in filas
            if f["t"]}


def statement(household, year: int, month: int | None = None) -> Statement:
    """Lo que entró, lo que salió y lo que quedó, contra el periodo anterior."""

    from django.utils.formats import date_format

    desde, hasta = _periodo(year, month)
    ano_prev, mes_prev = _anterior(year, month)
    desde_prev, hasta_prev = _periodo(ano_prev, mes_prev)

    with use_household(household):
        ingresos = _por_categoria(Account.Type.INCOME, desde, hasta)
        gastos = _por_categoria(Account.Type.EXPENSE, desde, hasta)
        ingresos_prev = _por_categoria(Account.Type.INCOME, desde_prev,
                                       hasta_prev)
        gastos_prev = _por_categoria(Account.Type.EXPENSE, desde_prev,
                                     hasta_prev)

    def _lineas(actual: dict, anterior: dict) -> list:
        # Las categorías que desaparecieron también salen, con cero: que algo
        # deje de gastarse es tan informativo como que empiece.
        etiquetas = sorted(set(actual) | set(anterior),
                           key=lambda k: -(actual.get(k) or 0))
        return [StatementLine(label=e, amount=actual.get(e, 0),
                              previous=anterior.get(e, 0))
                for e in etiquetas]

    etiqueta = (date_format(desde, "F Y") if month else str(year))
    etiqueta_prev = (date_format(desde_prev, "F Y") if mes_prev
                     else str(ano_prev))
    return Statement(
        label=etiqueta.capitalize(), starts_on=desde, ends_on=hasta,
        income=_lineas(ingresos, ingresos_prev),
        expenses=_lineas(gastos, gastos_prev),
        previous_label=etiqueta_prev.capitalize(),
    )
