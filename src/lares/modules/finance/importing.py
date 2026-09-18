"""Conciliar lo que dice el banco con lo que dice tu libro.

Tres resultados posibles para cada movimiento del estado de cuenta:

    ya esta      un asiento tuyo coincide -> no se toca nada
    encaja       hay un asiento parecido  -> se enlaza, no se duplica
    es nuevo     no hay nada parecido     -> se propone crearlo

El segundo caso es el que evita el libro basura: registraste "Gasolina 980" el
martes y el banco lo reporta el jueves con otra descripcion. Son el mismo gasto.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from lares.core.models import Account, Entry, Posting
from lares.core.scoping import use_household

# Margen para dar por bueno un encaje: el banco suele reportar con retraso.
DIAS_TOLERANCIA = 4


@dataclass
class Row:
    movement: object
    status: str              # "known" | "match" | "new"
    entry: object = None
    account_guess: object = None

    @property
    def is_new(self) -> bool:
        return self.status == "new"


def reconcile(household, account, movements: list) -> list:
    """Clasifica cada movimiento contra lo que ya hay en el libro."""
    if not movements:
        return []

    with use_household(household):
        desde = min(m.date for m in movements) - dt.timedelta(days=DIAS_TOLERANCIA)
        hasta = max(m.date for m in movements) + dt.timedelta(days=DIAS_TOLERANCIA)

        existentes = list(
            Entry.objects.filter(date__gte=desde, date__lte=hasta)
            .prefetch_related("postings")
        )
        vistos = {e.external_ref for e in existentes if e.external_ref}
        usados = set()

        filas = []
        for mov in movements:
            huella = mov.fingerprint
            if huella in vistos:
                filas.append(Row(mov, "known"))
                continue

            encaje = _buscar(mov, account, existentes, usados)
            if encaje:
                usados.add(encaje.pk)
                filas.append(Row(mov, "match", entry=encaje))
            else:
                filas.append(Row(mov, "new"))
        return filas


def _buscar(mov, account, existentes, usados):
    """Un asiento del libro que sea, casi seguro, este mismo movimiento."""
    objetivo = abs(mov.amount)
    for entry in existentes:
        if entry.pk in usados:
            continue
        if abs((entry.date - mov.date).days) > DIAS_TOLERANCIA:
            continue
        for apunte in entry.postings.all():
            if apunte.account_id != account.pk:
                continue
            if abs(abs(apunte.amount) - objetivo) < Decimal("0.01"):
                return entry
    return None


@transaction.atomic
def apply(household, account, category, rows: list, source: str = "import") -> dict:
    """Crea lo nuevo y marca lo encajado. Nunca toca lo que ya estaba."""
    creados = enlazados = 0

    with use_household(household):
        for fila in rows:
            if fila.status == "known":
                continue

            if fila.status == "match" and fila.entry:
                # No se duplica: se le pone la referencia del banco para que la
                # proxima importacion lo reconozca sin heuristicas.
                if not fila.entry.external_ref:
                    fila.entry.external_ref = fila.movement.fingerprint
                    fila.entry.save(update_fields=["external_ref", "updated_at"])
                enlazados += 1
                continue

            mov = fila.movement
            entry = Entry.objects.create(
                household=household, date=mov.date,
                description=mov.description, source=source,
                external_ref=mov.fingerprint,
            )
            contrapartida = fila.account_guess or category
            # El signo del banco manda: negativo salio, positivo entro.
            Posting.objects.create(
                household=household, entry=entry, account=account, amount=mov.amount
            )
            Posting.objects.create(
                household=household, entry=entry, account=contrapartida,
                amount=-mov.amount,
            )
            creados += 1

    return {"created": creados, "linked": enlazados,
            "known": sum(1 for f in rows if f.status == "known")}


def default_category(household, sign: Decimal) -> Account | None:
    """Dónde va lo que no se sabe clasificar todavía.

    Mejor una cuenta «Sin clasificar» visible que inventar una categoría: lo
    primero se arregla en una tarde, lo segundo ensucia los informes para
    siempre.
    """
    tipo = Account.Type.EXPENSE if sign < 0 else Account.Type.INCOME
    nombre = "Sin clasificar" if sign < 0 else "Ingresos sin clasificar"
    with use_household(household):
        cuenta, _ = Account.objects.get_or_create(
            household=household, name=nombre, type=tipo,
            defaults={"currency": household.currency},
        )
    return cuenta
