#!/bin/sh
# Arranque de un contenedor de Lares.
#
# Hace tres cosas antes de ceder el control al proceso de verdad:
#
#   1. Espera a que la base conteste. Sin esto, levantar la pila entera de golpe
#      es una carrera que se pierde una vez de cada tres.
#   2. Aplica las migraciones **bajo un candado de Postgres**. Web, worker y
#      beat arrancan a la vez y los tres migrarian: dos migrando la misma tabla
#      al mismo tiempo deja la base a medias, que es la peor forma de estrenar
#      una version.
#   3. Recoge los estaticos, que cambian con cada version.
#
# Todo es idempotente: reiniciar un contenedor cien veces deja el mismo estado.
set -e

cd /app

espera_a_la_base() {
    intentos=0
    until python src/manage.py check --database default >/dev/null 2>&1; do
        intentos=$((intentos + 1))
        if [ "$intentos" -gt 60 ]; then
            echo "La base no contesta despues de 60 intentos. Abandono." >&2
            exit 1
        fi
        echo "Esperando a la base de datos... ($intentos)"
        sleep 2
    done
}

migra_con_candado() {
    # El candado es de la sesion: si el contenedor muere a media migracion,
    # Postgres lo suelta solo y el siguiente arranque lo vuelve a intentar.
    python - <<'PY'
import django, os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lares.settings.prod")
sys.path.insert(0, "src")
django.setup()

from django.core.management import call_command
from django.db import connection

CANDADO = 8712345678901234   # arbitrario y fijo: identifica "migrar Lares"

with connection.cursor() as cursor:
    cursor.execute("SELECT pg_advisory_lock(%s)", [CANDADO])
    try:
        call_command("migrate", interactive=False, verbosity=1)
    finally:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [CANDADO])
PY
}

espera_a_la_base

if [ "${LARES_MIGRATE_ON_START:-1}" = "1" ]; then
    migra_con_candado
fi

if [ "${LARES_COLLECTSTATIC:-1}" = "1" ]; then
    python src/manage.py collectstatic --noinput >/dev/null
fi

exec "$@"
