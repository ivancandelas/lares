#!/usr/bin/env bash
# Actualizar Lares sin perder nada.
#
# El orden no es negociable y es la razón de que esto sea un script y no tres
# órdenes sueltas que alguien teclea de memoria a las once de la noche:
#
#   1. copia de seguridad ANTES de tocar nada;
#   2. bajar la imagen nueva (si falla, no se ha roto nada todavía);
#   3. levantar;
#   4. comprobar que contesta y que es la versión que se esperaba.
#
# Si el paso 4 falla, se dice cómo volver atrás. No se vuelve solo: deshacer
# una migración por nuestra cuenta puede destruir datos, y a esa hora lo que
# hace falta es una instrucción clara, no automatismo.
set -euo pipefail

COMPOSE="${COMPOSE:-docker compose -f compose.prod.yaml}"
ETIQUETA="${1:-${LARES_TAG:-latest}}"
COPIAS="${LARES_BACKUP_DIR:-./data/backups}"

anterior() {
    $COMPOSE exec -T web sh -lc 'echo -n "$LARES_VERSION"' 2>/dev/null || echo "desconocida"
}

echo "==> Versión que corre ahora: $(anterior)"
echo "==> Actualizando a: $ETIQUETA"

mkdir -p "$COPIAS"
SELLO="$(date +%Y%m%d-%H%M%S)"
echo "==> 1/4 Copia de seguridad en $COPIAS/lares-$SELLO.sql.gz"
$COMPOSE exec -T db pg_dump -U lares lares | gzip > "$COPIAS/lares-$SELLO.sql.gz"
echo "    $(du -h "$COPIAS/lares-$SELLO.sql.gz" | cut -f1)"

echo "==> 2/4 Bajando la imagen"
LARES_TAG="$ETIQUETA" $COMPOSE pull

echo "==> 3/4 Levantando"
LARES_TAG="$ETIQUETA" $COMPOSE up -d

echo "==> 4/4 Comprobando"
for intento in $(seq 1 30); do
    RESPUESTA="$(curl -fsS "http://127.0.0.1:${LARES_PORT:-8000}/salud" 2>/dev/null || true)"
    if [ -n "$RESPUESTA" ]; then
        echo "    $RESPUESTA"
        echo "==> Listo. Si algo va mal, para volver atrás:"
        echo "    LARES_TAG=<la de antes> $COMPOSE up -d"
        echo "    zcat $COPIAS/lares-$SELLO.sql.gz | $COMPOSE exec -T db psql -U lares lares"
        exit 0
    fi
    sleep 2
done

echo "!!! No contesta después de un minuto. La copia está en $COPIAS/lares-$SELLO.sql.gz" >&2
echo "    Para volver atrás:" >&2
echo "    LARES_TAG=<la de antes> $COMPOSE up -d" >&2
echo "    Y si la migración dejó la base a medias:" >&2
echo "    zcat $COPIAS/lares-$SELLO.sql.gz | $COMPOSE exec -T db psql -U lares lares" >&2
exit 1
