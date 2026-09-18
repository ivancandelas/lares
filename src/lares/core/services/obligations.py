"""Motor de obligaciones.

Recorre los proveedores registrados por los modulos, materializa lo que
devuelven y crea los recordatorios. Es idempotente de punta a punta: correrlo
diez veces seguidas produce exactamente el mismo estado que correrlo una.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from ..models import Obligation, Reminder, Resource
from ..registry import registry
from ..scoping import use_household

logger = logging.getLogger(__name__)

DEFAULT_OFFSETS = (-30, -15, -7, -1)


@transaction.atomic
def materialize(household, on_date: dt.date | None = None) -> dict:
    """Genera/actualiza las obligaciones de un hogar. Devuelve un resumen."""
    on_date = on_date or dt.date.today()
    created = updated = 0

    with use_household(household):
        # Se itera por tipo registrado, no sobre Resource: la herencia
        # multi-tabla devolveria instancias de Resource, sin los campos ni los
        # metodos de la subclase que el proveedor necesita.
        for kind, model in registry.resource_kinds.items():
            providers = registry.providers_for(kind)
            if not providers:
                continue
            for resource in model.objects.filter(status=Resource.Status.ACTIVE):
                for provider in providers:
                    for spec in provider.generate(resource, on_date) or []:
                        obligation, was_created = _upsert(household, resource, provider, spec)
                        created += was_created
                        updated += not was_created
                        _sync_reminders(obligation)

    return {"created": created, "updated": updated, "date": on_date}


def _upsert(household, subject, provider, spec):
    ctype = ContentType.objects.get_for_model(subject.__class__)
    obligation, created = Obligation.all_objects.update_or_create(
        household=household,
        dedupe_key=spec.dedupe_key,
        defaults={
            "title": spec.title,
            "subject_type": ctype,
            "subject_id": subject.pk,
            "due_on": spec.due_on,
            "amount": spec.amount,
            "currency": spec.currency or household.currency,
            "severity": spec.severity,
            "source": provider.key,
            "remind_offsets": list(spec.remind_offsets or DEFAULT_OFFSETS),
        },
    )
    return obligation, created


def _sync_reminders(obligation):
    if obligation.status != Obligation.Status.PENDING:
        return
    for offset in obligation.remind_offsets or DEFAULT_OFFSETS:
        fire_on = obligation.due_on + dt.timedelta(days=int(offset))
        Reminder.all_objects.get_or_create(
            household_id=obligation.household_id,
            obligation=obligation,
            fire_on=fire_on,
            channel="email",
        )


def mark_overdue(household, on_date: dt.date | None = None) -> int:
    on_date = on_date or dt.date.today()
    with use_household(household):
        return Obligation.objects.filter(
            status=Obligation.Status.PENDING, due_on__lt=on_date
        ).update(status=Obligation.Status.OVERDUE)
