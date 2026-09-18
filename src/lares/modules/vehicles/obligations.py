"""Proveedores de obligaciones del modulo de vehiculos.

Nota deliberada: las reglas mexicanas (verificacion, refrendo) estan aqui de
forma provisional para tener algo funcionando. Su destino correcto es un pack
de jurisdiccion en YAML, porque cambian por estado y por ano y no deben
requerir un despliegue. Ver packs/ y docs/03-module-system.md
"""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec


class VerificacionProvider(ObligationProvider):
    key = "vehicles.verificacion"
    label = "Verificacion vehicular"
    applies_to = "vehicle"

    # Calendario por ultimo digito de placa (esquema tipico en Mexico).
    SEMESTER_BY_DIGIT = {5: 1, 6: 1, 7: 2, 8: 2, 3: 3, 4: 3, 1: 4, 2: 4, 9: 5, 0: 5}

    def generate(self, vehicle, on_date: dt.date):
        digit = vehicle.last_plate_digit
        if digit is None:
            return []
        month = self.SEMESTER_BY_DIGIT[digit] * 2
        specs = []
        for half, base_month in ((1, month), (2, month + 6)):
            year = on_date.year
            due = dt.date(year, ((base_month - 1) % 12) + 1, 28)
            if due < on_date:
                due = due.replace(year=year + 1)
            specs.append(ObligationSpec(
                dedupe_key=f"vehicle:{vehicle.pk}:verificacion:{due:%Y-%m}",
                title=f"Verificacion vehicular - {vehicle}",
                due_on=due,
                severity="high",
                remind_offsets=(-45, -20, -7, -1),
                payload={"half": half},
            ))
        return specs


class RefrendoProvider(ObligationProvider):
    key = "vehicles.refrendo"
    label = "Refrendo / tenencia"
    applies_to = "vehicle"

    def generate(self, vehicle, on_date: dt.date):
        year = on_date.year if on_date.month <= 3 else on_date.year + 1
        due = dt.date(year, 3, 31)
        return [ObligationSpec(
            dedupe_key=f"vehicle:{vehicle.pk}:refrendo:{year}",
            title=f"Refrendo {year} - {vehicle}",
            due_on=due,
            severity="high",
            remind_offsets=(-60, -30, -7),
        )]


class ServiceIntervalProvider(ObligationProvider):
    key = "vehicles.service"
    label = "Servicio de mantenimiento"
    applies_to = "vehicle"

    def generate(self, vehicle, on_date: dt.date):
        if not (vehicle.service_interval_km and vehicle.odometer_km):
            return []
        next_km = (vehicle.last_service_km or 0) + vehicle.service_interval_km
        remaining = next_km - vehicle.odometer_km
        rate = vehicle.avg_km_per_month or 1000
        due = on_date + dt.timedelta(days=int(max(remaining, 0) / rate * 30))
        return [ObligationSpec(
            dedupe_key=f"vehicle:{vehicle.pk}:service:{next_km}",
            title=f"Servicio {next_km:,} km - {vehicle}",
            due_on=due,
            severity="normal" if remaining > 500 else "high",
            remind_offsets=(-30, -7),
            payload={"target_km": next_km, "remaining_km": remaining},
        )]
