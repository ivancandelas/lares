"""Datos de demostracion para ver el sistema funcionando.

El nucleo crea el hogar y las partes basicas; cada modulo siembra lo suyo a
traves de `registry.demo_seeder`. Asi este comando no importa ningun modulo.
Solo para desarrollo.
"""

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from lares.core.models import Household, Location, Party
from lares.core.registry import registry
from lares.core.scoping import use_household
from lares.core.services import checks, obligations


class Command(BaseCommand):
    help = "Siembra un hogar de ejemplo con datos suficientes para ver el tablero."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Casa de ejemplo")

    def handle(self, *args, **options):
        name = options["name"]
        household, _ = Household.objects.get_or_create(
            slug=slugify(name), defaults={"name": name}
        )

        with use_household(household):
            Party.objects.get_or_create(
                household=household, name="Titular", defaults={"is_self": True}
            )
            Party.objects.get_or_create(
                household=household, name="Aseguradora GNP",
                defaults={"kind": Party.Kind.ORGANIZATION},
            )
            Location.objects.get_or_create(household=household, name="Cochera")

            for seeder in registry.demo_seeders:
                summary = seeder(household)
                if summary:
                    self.stdout.write(f"  {summary}")

        result = obligations.materialize(household)
        findings = checks.run_all(household)
        self.stdout.write(self.style.SUCCESS(
            f"Hogar '{household.name}' listo. "
            f"Obligaciones nuevas: {result['created']}. Huecos detectados: {len(findings)}."
        ))
