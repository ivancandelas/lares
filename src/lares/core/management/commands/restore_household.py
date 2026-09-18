"""Restaura un hogar desde una copia cifrada."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from lares.core.services import backup

from .backup_household import read_passphrase


class Command(BaseCommand):
    help = "Restaura un hogar desde una copia de seguridad cifrada."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--passphrase-file", help="archivo con la frase de paso")

    def handle(self, *args, **options):
        ruta = Path(options["file"])
        if not ruta.exists():
            raise CommandError(f"No existe {ruta}")

        frase = read_passphrase(options.get("passphrase_file"))
        try:
            result = backup.restore_household(ruta, frase)
        except backup.BadPassphrase as exc:
            raise CommandError(str(exc)) from exc

        total = sum(result["restored"].values())
        self.stdout.write(self.style.SUCCESS(
            f"{result['household']['name']}: {total} registros y "
            f"{result['files']} archivos restaurados"
        ))
