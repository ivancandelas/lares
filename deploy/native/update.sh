#!/usr/bin/env bash
# Actualizar una instalación nativa de Lares.
#
# Mismo orden que la de Docker, por la misma razón: copia antes de tocar nada,
# y si algo falla se dice cómo volver en vez de intentarlo solo.
#
#   lares-update            a la última publicada
#   lares-update 0.7.0      a una concreta
#   lares-update --rollback a la anterior
#
# Volver atrás aquí es barato de verdad: cada versión vive en su carpeta con su
# propio entorno, así que es mover un enlace y reiniciar. No se restaura nada.
set -euo pipefail

RAIZ="/opt/lares"
REPO="${LARES_REPO:-ivancandelas/lares}"
USUARIO="lares"

rojo() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
paso() { printf '\033[36m==>\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { rojo "Esto se ejecuta como root."; exit 1; }
[ -L "$RAIZ/current" ] || { rojo "No hay una instalación de Lares en $RAIZ."; exit 1; }

# La versión a la que ir. Se pregunta primero por el Release publicado y, si no
# hay ninguno, por la etiqueta más nueva.
#
# El orden importa y la segunda mitad no es paranoia: empujar una etiqueta NO
# crea un Release en GitHub. Sin este respaldo, quien acaba de publicar su
# primera versión ve morir la instalación con un «404» crudo justo después de
# veinte minutos instalando dependencias, y no hay nada en ese mensaje que diga
# qué le falta.
ultima_version() {
    local v
    v="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -1 || true)"
    [ -n "$v" ] || v="$(curl -fsSL "https://api.github.com/repos/$REPO/tags" 2>/dev/null \
        | sed -n 's/.*"name": *"v\{0,1\}\([^"]*\)".*/\1/p' | sort -V | tail -1 || true)"
    printf '%s' "$v"
}

sin_versiones() {
    rojo "No hay ninguna versión publicada en $REPO."
    rojo "Publica una:   make release V=0.7.0 && git push --follow-tags"
    rojo "O pásala:      $1 0.7.0"
    exit 1
}

ACTUAL="$(basename "$(readlink -f "$RAIZ/current")")"

# --- Volver atrás -----------------------------------------------------------
if [ "${1:-}" = "--rollback" ]; then
    ANTERIOR="$(ls -1 "$RAIZ/releases" | grep -v "^$ACTUAL$" | sort -V | tail -1)"
    [ -n "$ANTERIOR" ] || { rojo "No hay otra versión a la que volver."; exit 1; }
    paso "Volviendo de $ACTUAL a $ANTERIOR"
    ln -sfn "$RAIZ/releases/$ANTERIOR" "$RAIZ/current"
    systemctl restart lares-web lares-worker lares-beat
    paso "Hecho. Si la migración de $ACTUAL cambió la base, restaura la copia:"
    echo "    ls $RAIZ/backups/"
    exit 0
fi

# --- Qué versión ------------------------------------------------------------
NUEVA="${1:-}"
if [ -z "$NUEVA" ]; then
    NUEVA="$(ultima_version)"
    [ -n "$NUEVA" ] || sin_versiones lares-update
fi

if [ "$NUEVA" = "$ACTUAL" ]; then
    paso "Ya corre la $ACTUAL. No hay nada que hacer."
    exit 0
fi
paso "De $ACTUAL a $NUEVA"

# --- 1. Copia ---------------------------------------------------------------
SELLO="$(date +%Y%m%d-%H%M%S)"
COPIA="$RAIZ/backups/lares-$ACTUAL-$SELLO.sql.gz"
paso "1/5 Copia de la base en $COPIA"
sudo -u postgres pg_dump lares | gzip > "$COPIA"
paso "    $(du -h "$COPIA" | cut -f1)"

# --- 2. Bajar ---------------------------------------------------------------
paso "2/5 Bajando $NUEVA"
DESTINO="$RAIZ/releases/$NUEVA"
if [ ! -d "$DESTINO" ]; then
    mkdir -p "$DESTINO"
    if [ -n "${LARES_SOURCE_DIR:-}" ]; then
        cp -a "$LARES_SOURCE_DIR"/. "$DESTINO"/
    else
        curl -fsSL "https://github.com/$REPO/archive/refs/tags/v$NUEVA.tar.gz" \
            | tar -xz --strip-components=1 -C "$DESTINO"
    fi
fi
cd "$DESTINO"
uv sync --no-dev --quiet
chown -R "$USUARIO:$USUARIO" "$DESTINO"

# --- 3. Migrar --------------------------------------------------------------
# Se migra con el código NUEVO y los servicios todavía parados: una migración
# aplicada mientras la versión vieja sigue sirviendo es la receta de los errores
# que nadie reproduce después.
paso "3/5 Migrando"
systemctl stop lares-web lares-worker lares-beat
set -a; . "$RAIZ/lares.env"; set +a
export DJANGO_SETTINGS_MODULE=lares.settings.prod PYTHONPATH="$DESTINO/src"
sudo -u "$USUARIO" --preserve-env "$DESTINO/.venv/bin/python" src/manage.py migrate_locked
sudo -u "$USUARIO" --preserve-env "$DESTINO/.venv/bin/python" src/manage.py collectstatic --noinput >/dev/null

# --- 4. Cambiar el enlace y arrancar ---------------------------------------
paso "4/5 Cambiando a $NUEVA"
install -m 644 "$DESTINO/deploy/native/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload

# Se rehacen los enlaces de las órdenes, igual que las units. No es
# decorativo: una instalación vieja puede tenerlos solo en `/usr/local/bin`, y
# ahí no los ve la shell que abre `pct enter`. Actualizar es el momento en que
# eso se corrige sin que nadie tenga que enterarse.
for bin_dir in /usr/local/bin /usr/bin; do
    ln -sf "$RAIZ/current/deploy/native/update.sh" "$bin_dir/lares-update"
    ln -sf "$RAIZ/current/deploy/native/lares-manage" "$bin_dir/lares-manage"
done
ln -sfn "$DESTINO" "$RAIZ/current"
systemctl start lares-web lares-worker lares-beat

# --- 5. Comprobar -----------------------------------------------------------
paso "5/5 Comprobando"
for _ in $(seq 1 30); do
    RESPUESTA="$(curl -fsS http://127.0.0.1:8000/salud 2>/dev/null || true)"
    if [ -n "$RESPUESTA" ]; then
        echo "    $RESPUESTA"
        paso "Listo."
        # Se guardan tres versiones: la que corre, la anterior por si acaso, y
        # una más. Cada una ocupa su entorno virtual entero.
        ls -1 "$RAIZ/releases" | sort -V | head -n -3 | while read -r vieja; do
            [ "$vieja" = "$ACTUAL" ] || rm -rf "${RAIZ:?}/releases/$vieja"
        done
        exit 0
    fi
    sleep 2
done

rojo "No contesta después de un minuto."
rojo "Para volver atrás:   lares-update --rollback"
rojo "La copia está en:    $COPIA"
rojo "Y qué pasó:          journalctl -u lares-web -n 50"
exit 1
