"""Envio de recordatorios.

Idempotente por construccion: un recordatorio con `sent_at` ya puesto no se
vuelve a enviar nunca. Es la propiedad que permite reintentar la tarea, cambiar
el horario del planificador o redesplegar sin que al usuario le lleguen avisos
repetidos, que es la forma mas rapida de que deje de leerlos.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import Membership, Obligation, Reminder
from ..scoping import use_household

logger = logging.getLogger(__name__)


def send_due_reminders(household, on_date: dt.date | None = None) -> dict:
    on_date = on_date or dt.date.today()
    recipients = _recipients(household)
    sent = skipped = 0

    with use_household(household):
        pendientes = (
            Reminder.objects
            .filter(fire_on__lte=on_date, sent_at__isnull=True)
            .select_related("obligation")
            .order_by("fire_on")
        )
        for reminder in pendientes:
            if reminder.obligation.status != Obligation.Status.PENDING:
                # La obligacion ya se cumplio: el aviso se cierra sin enviarse.
                _mark(reminder)
                skipped += 1
                continue
            if not recipients:
                skipped += 1
                continue
            if _deliver(household, reminder, recipients):
                _mark(reminder)
                sent += 1
            else:
                skipped += 1

    return {"sent": sent, "skipped": skipped, "date": on_date}


def _recipients(household) -> list[str]:
    return list(
        Membership.objects.filter(household=household, user__isnull=False)
        .values_list("user__email", flat=True)
    ) or list(
        household.members.values_list("email", flat=True)
    )


def _deliver(household, reminder, recipients) -> bool:
    obligation = reminder.obligation
    dias = (obligation.due_on - reminder.fire_on).days
    context = {
        "obligation": obligation,
        "dias": dias,
        "household": household,
        "product_name": settings.PRODUCT_NAME,
    }
    try:
        send_mail(
            subject=render_to_string("core/email/reminder_subject.txt", context).strip(),
            message=render_to_string("core/email/reminder_body.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("No se pudo enviar el recordatorio %s", reminder.pk)
        return False


@transaction.atomic
def _mark(reminder):
    reminder.sent_at = timezone.now()
    reminder.save(update_fields=["sent_at", "updated_at"])
