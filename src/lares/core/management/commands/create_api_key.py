"""Crea una llave de API. El texto completo se muestra una sola vez."""

from django.core.management.base import BaseCommand, CommandError

from lares.core.models import ApiKey, Household
from lares.core.scoping import use_household


class Command(BaseCommand):
    help = "Crea una llave de API para un hogar."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Llave sin nombre")
        parser.add_argument("--household", help="slug del hogar (por defecto, el primero)")

    def handle(self, *args, **options):
        household = (
            Household.objects.filter(slug=options["household"]).first()
            if options["household"] else Household.objects.first()
        )
        if not household:
            raise CommandError("No hay ningún hogar.")

        with use_household(household):
            key, token = ApiKey.issue(household, options["name"])

        self.stdout.write(self.style.SUCCESS(f"Llave '{key.name}' creada para {household.name}"))
        self.stdout.write("")
        self.stdout.write(f"  {token}")
        self.stdout.write("")
        self.stdout.write("No se vuelve a mostrar: guárdala ahora. Se envía en X-Lares-Key.")
