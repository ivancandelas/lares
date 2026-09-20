"""Migrar sin que dos procesos se pisen.

Web, worker y reloj arrancan a la vez, y en una actualizacion los tres querrian
migrar. Dos migraciones simultaneas sobre la misma tabla dejan la base a medias,
que es la peor forma de estrenar una version.

El candado es de sesion (`pg_advisory_lock`): si el proceso muere a media
migracion, Postgres lo suelta solo y el siguiente arranque lo reintenta. No hay
que limpiar nada a mano, que es justo lo que nadie recuerda hacer a las once de
la noche.

Lo usan el arranque del contenedor y el actualizador de la instalacion nativa,
para que la regla viva en un solo sitio.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection

# Arbitrario y fijo: identifica "migrar Lares" dentro de esta base.
CANDADO = 8712345678901234


class Command(BaseCommand):
    help = "Aplica las migraciones bajo un candado, para que solo migre uno."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout", type=int, default=600,
            help="Segundos que se espera al que esté migrando antes de rendirse.",
        )

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = %s",
                           [f"{options['timeout']}s"])
            cursor.execute("SELECT pg_advisory_lock(%s)", [CANDADO])
            try:
                call_command("migrate", interactive=False,
                             verbosity=options.get("verbosity", 1))
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [CANDADO])
