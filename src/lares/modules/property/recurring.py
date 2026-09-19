"""Agua, luz, gas, internet: lo que cobra cada servicio del inmueble."""

import datetime as dt

from django.urls import reverse

from lares.core.registry import Recurring

from .models import Service


def recurring(household) -> list:
    hoy = dt.date.today()
    salida = []
    for servicio in Service.objects.filter(status=Service.Status.ACTIVE):
        proximo = None
        if servicio.due_day:
            import calendar

            proximo = dt.date(hoy.year, hoy.month,
                              min(servicio.due_day,
                                  calendar.monthrange(hoy.year, hoy.month)[1]))
            if proximo < hoy:
                mes = hoy.month % 12 + 1
                ano = hoy.year + (1 if mes == 1 else 0)
                proximo = dt.date(ano, mes,
                                  min(servicio.due_day,
                                      calendar.monthrange(ano, mes)[1]))
        salida.append(Recurring(
            title=f"{servicio.get_service_kind_display()} · "
                  f"{servicio.property_ref.name}",
            # El importe habitual es una estimacion, no una factura: se dice
            # como tal en la nota para que nadie lo tome por exacto.
            amount=servicio.typical_amount,
            cycle=servicio.cycle,
            currency=servicio.currency,
            counterparty=servicio.provider,
            next_on=proximo,
            url=reverse("core:resource-detail", args=[servicio.pk]),
            source="property",
            note="importe habitual" if servicio.typical_amount else "importe variable",
        ))
    return salida
