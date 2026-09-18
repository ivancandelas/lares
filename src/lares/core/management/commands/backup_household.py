"""Copia cifrada de un hogar."""

import datetime as dt
import getpass
import os
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from lares.core.models import Household
from lares.core.services import backup


class Command(BaseCommand):
    help = "Crea una copia de seguridad cifrada de un hogar."

    def add_arguments(self, parser):
        parser.add_argument("--household", help="slug del hogar (por defecto, el primero)")
        parser.add_argument("--out", help="ruta del archivo de salida")
        parser.add_argument("--passphrase-file", help="archivo con la frase de paso")

    def handle(self, *args, **options):
        household = (
            Household.objects.filter(slug=options["household"]).first()
            if options["household"] else Household.objects.first()
        )
        if not household:
            raise CommandError("No hay ningún hogar que copiar.")

        frase = read_passphrase(options.get("passphrase_file"), confirm=True)
        destino = Path(options["out"] or
                       f"lares-backup-{household.slug}-{dt.date.today():%Y%m%d}.lares")
        ruta = backup.backup_household(household, destino, frase)
        self.stdout.write(self.style.SUCCESS(
            f"{household.name} copiado a {ruta} ({ruta.stat().st_size:,} bytes, cifrado)"
        ))
        self.stdout.write("Sin esa frase, esta copia no se puede abrir. Guárdala aparte.")


def read_passphrase(passphrase_file=None, confirm=False) -> str:
    """La frase nunca va como argumento: quedaría visible en la lista de procesos."""
    if passphrase_file:
        return Path(passphrase_file).read_text(encoding="utf-8").strip()

    desde_entorno = os.environ.get("LARES_BACKUP_PASSPHRASE")
    if desde_entorno:
        return desde_entorno

    if not sys.stdin.isatty():
        raise CommandError(
            "Indica la frase en LARES_BACKUP_PASSPHRASE o con --passphrase-file."
        )

    frase = getpass.getpass("Frase de paso: ")
    if confirm and frase != getpass.getpass("Repítela: "):
        raise CommandError("Las frases no coinciden.")
    if not frase:
        raise CommandError("La frase no puede estar vacía.")
    return frase
