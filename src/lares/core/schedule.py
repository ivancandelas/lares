"""Evaluacion de calendarios declarativos.

Traduce la parte `schedule` de una regla -venga de un pack YAML o de una regla
creada por el usuario- a fechas concretas. Vive en el nucleo porque tanto los
packs de jurisdiccion como las reglas propias del usuario lo necesitan.

Formas soportadas:

    {"yearly":  {"month": 3, "day": 31}}        cada ano, mismo dia
    {"monthly": {"day": 15}}                    cada mes
    {"every":   {"months": 6}, "from": "2026-01-15"}
    {"on_date": "2027-04-30"}                   una sola vez
    {"on_expiry": true}                         usa la fecha que se le pase
"""

from __future__ import annotations

import calendar
import datetime as dt


def _clamp(year: int, month: int, day: int) -> dt.date:
    """Un 31 en un mes de 30 dias cae al ultimo dia real, no revienta."""
    year += (month - 1) // 12
    month = ((month - 1) % 12) + 1
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_occurrences(
    schedule: dict,
    on_date: dt.date,
    count: int = 2,
    expires_on: dt.date | None = None,
) -> list[dt.date]:
    """Proximas `count` fechas a partir de `on_date` (inclusive)."""
    if not schedule:
        return []

    if schedule.get("on_expiry"):
        return [expires_on] if expires_on else []

    if "on_date" in schedule:
        once = _as_date(schedule["on_date"])
        return [once] if once and once >= on_date else []

    if "yearly" in schedule:
        cfg = schedule["yearly"]
        month, day = int(cfg.get("month", 1)), int(cfg.get("day", 1))
        out, year = [], on_date.year
        while len(out) < count:
            candidate = _clamp(year, month, day)
            if candidate >= on_date:
                out.append(candidate)
            year += 1
        return out

    if "monthly" in schedule:
        day = int(schedule["monthly"].get("day", 1))
        out, year, month = [], on_date.year, on_date.month
        while len(out) < count:
            candidate = _clamp(year, month, day)
            if candidate >= on_date:
                out.append(candidate)
            month += 1
            if month > 12:
                month, year = 1, year + 1
        return out

    if "every" in schedule:
        months = int(schedule["every"].get("months", 1))
        start = _as_date(schedule.get("from")) or on_date
        out, cursor = [], start
        # Avanza hasta alcanzar hoy y luego toma las siguientes.
        guard = 0
        while cursor < on_date and guard < 1200:
            cursor = _clamp(cursor.year, cursor.month + months, start.day)
            guard += 1
        while len(out) < count:
            out.append(cursor)
            cursor = _clamp(cursor.year, cursor.month + months, start.day)
        return out

    return []


def _as_date(value) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None
