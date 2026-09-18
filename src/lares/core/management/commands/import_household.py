"""Restaura un hogar desde un export."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from lares.core.services import portability


class Command(BaseCommand):
    help = "Restaura un hogar desde un archivo .zip exportado."

    def add_arguments(self, parser):
        parser.add_argument("file")

    def handle(self, *args, **options):
        ruta = Path(options["file"])
        if not ruta.exists():
            raise CommandError(f"No existe {ruta}")

        result = portability.import_household(ruta)
        total = sum(result["restored"].values())
        self.stdout.write(self.style.SUCCESS(
            f"{result['household']['name']}: {total} registros y "
            f"{result['files']} archivos restaurados"
        ))
        for modelo, n in sorted(result["restored"].items()):
            self.stdout.write(f"  {modelo}: {n}")
