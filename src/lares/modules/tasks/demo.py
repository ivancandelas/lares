"""Datos de ejemplo del modulo de tareas."""

import datetime as dt

from .models import Task


def seed(household) -> str:
    hoy = dt.date.today()
    ejemplos = [
        ("Cotizar seguro del Mazda", hoy + dt.timedelta(days=4), Task.Priority.HIGH),
        ("Buscar la factura del refrigerador", hoy - dt.timedelta(days=3), Task.Priority.NORMAL),
        ("Agendar servicio del boiler", hoy + dt.timedelta(days=21), Task.Priority.NORMAL),
    ]
    for title, due, priority in ejemplos:
        Task.objects.get_or_create(
            household=household, title=title,
            defaults={"due_on": due, "priority": priority},
        )
    return f"tareas: {Task.objects.count()}"
