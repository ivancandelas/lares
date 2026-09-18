"""Envia los recordatorios vencidos. Equivalente manual de la tarea programada."""

from django.core.management.base import BaseCommand

from lares.core.models import Household
from lares.core.services import notify


class Command(BaseCommand):
    help = "Envia los recordatorios cuya fecha ya llego y que aun no se enviaron."

    def handle(self, *args, **options):
        for household in Household.objects.all():
            result = notify.send_due_reminders(household)
            self.stdout.write(self.style.SUCCESS(
                f"{household.name}: {result['sent']} enviados, {result['skipped']} omitidos"
            ))
