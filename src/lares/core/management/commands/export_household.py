"""Exporta un hogar completo a un .zip con formato documentado."""

import datetime as dt
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from lares.core.models import Household
from lares.core.services import portability


class Command(BaseCommand):
    help = "Exporta todo un hogar a un archivo .zip."

    def add_arguments(self, parser):
        parser.add_argument("--household", help="slug del hogar (por defecto, el primero)")
        parser.add_argument("--out", help="ruta del archivo de salida")

    def handle(self, *args, **options):
        household = (
            Household.objects.filter(slug=options["household"]).first()
            if options["household"] else Household.objects.first()
        )
        if not household:
            raise CommandError("No hay ningún hogar que exportar.")

        destino = Path(options["out"] or
                       f"lares-export-{household.slug}-{dt.date.today():%Y%m%d}.zip")
        ruta = portability.export_household(household, destino)
        self.stdout.write(self.style.SUCCESS(
            f"{household.name} exportado a {ruta} ({ruta.stat().st_size:,} bytes)"
        ))
        self.stdout.write("Contiene datos personales y cuentas de acceso: trátalo como un secreto.")
