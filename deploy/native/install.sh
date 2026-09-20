#!/usr/bin/env bash
# Instalación nativa de Lares: sin Docker, con systemd.
#
# Pensada para un LXC de Proxmox o cualquier Debian/Ubuntu limpio. Deja:
#
#   /opt/lares/releases/<versión>/   el código y su entorno, uno por versión
#   /opt/lares/current               enlace a la que corre ahora
#   /opt/lares/data/                 medios y el reloj de celery
#   /opt/lares/backups/              copias antes de cada actualización
#   /opt/lares/lares.env             la configuración, con los secretos
#
# **Una versión por carpeta y un enlace que apunta a la buena.** Es lo que hace
# que volver atrás sea mover el enlace y reiniciar, en vez de restaurar una
# copia y rezar. Cada versión lleva su propio entorno virtual, así que volver
# atrás recupera también las dependencias de entonces.
set -euo pipefail

VERSION="${1:-}"
REPO="${LARES_REPO:-ivancandelas/lares}"
RAIZ="/opt/lares"
USUARIO="lares"

rojo() { printf '\033[31m%s\033[0m\n' "$*" >&2; }
paso() { printf '\033[36m==>\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { rojo "Esto se instala como root."; exit 1; }

if [ -z "$VERSION" ]; then
    paso "Buscando la última versión publicada"
    VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
        | sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -1)"
    [ -n "$VERSION" ] || { rojo "No pude averiguar la última versión. Pásala: install.sh 0.7.0"; exit 1; }
fi
paso "Instalando Lares $VERSION"

# --- Lo que hace falta debajo ----------------------------------------------
paso "Dependencias del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    postgresql redis-server python3 python3-venv curl ca-certificates \
    libpq-dev build-essential poppler-utils >/dev/null

command -v uv >/dev/null || {
    paso "Instalando uv"
    curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh >/dev/null
}

# --- Usuario y carpetas -----------------------------------------------------
id "$USUARIO" >/dev/null 2>&1 || useradd --system --home "$RAIZ" --shell /usr/sbin/nologin "$USUARIO"
mkdir -p "$RAIZ"/{releases,data/media,backups}

# --- Base de datos ----------------------------------------------------------
# Primero arrancarla, y esperar a que conteste. En Debian el paquete la levanta
# sola al instalarse, pero "casi siempre" no es "siempre": en un contenedor
# recien creado la instalacion puede terminar antes de que el socket exista, y
# entonces el `createdb` de abajo falla por una carrera que no se repite al
# volver a ejecutarlo -que es la peor clase de fallo-.
systemctl enable --now postgresql redis-server >/dev/null 2>&1 || true

paso "Esperando a Postgres"
for _ in $(seq 1 30); do
    su - postgres -c "psql -tAc 'SELECT 1'" >/dev/null 2>&1 && break
    sleep 1
done
su - postgres -c "psql -tAc 'SELECT 1'" >/dev/null 2>&1 || {
    rojo "Postgres no arranca. Mira:  journalctl -u postgresql -n 30"
    exit 1
}

# La contraseña se genera aquí y se guarda en lares.env. Nadie la teclea, así
# que no hay razón para que sea corta ni para que se repita entre instalaciones.
if ! su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='lares'\"" | grep -q 1; then
    paso "Creando la base de datos"
    CLAVE_DB="$(openssl rand -hex 24)"
    su - postgres -c "psql -q -c \"CREATE USER lares WITH PASSWORD '$CLAVE_DB'\""
    su - postgres -c "createdb -O lares lares"
else
    CLAVE_DB=""      # ya existía: la contraseña buena está en lares.env
fi

# --- Configuración ----------------------------------------------------------
if [ ! -f "$RAIZ/lares.env" ]; then
    paso "Escribiendo la configuración"
    IP="$(hostname -I | awk '{print $1}')"
    cat > "$RAIZ/lares.env" <<ENV
# Configuración de Lares. Los secretos se generaron al instalar.
LARES_SECRET_KEY=$(openssl rand -hex 32)
LARES_DATABASE_URL=postgres://lares:${CLAVE_DB}@127.0.0.1:5432/lares
LARES_REDIS_URL=redis://127.0.0.1:6379/0
LARES_MEDIA_ROOT=$RAIZ/data/media

# Se entra por IP en la red de casa, así que no se exige HTTPS: con TLS
# obligatorio, todo respondería 301 hacia una dirección que no existe. Si algún
# día pones un proxy con dominio delante, pon esto a 1 y rellena las dos de
# abajo.
LARES_HTTPS=0
LARES_ALLOWED_HOSTS=$IP,localhost,127.0.0.1
LARES_SITE_URL=http://$IP:8000
# LARES_CSRF_TRUSTED_ORIGINS=https://lares.tudominio
ENV
    chmod 600 "$RAIZ/lares.env"
fi

# --- El código --------------------------------------------------------------
DESTINO="$RAIZ/releases/$VERSION"
if [ ! -d "$DESTINO" ]; then
    mkdir -p "$DESTINO"
    if [ -n "${LARES_SOURCE_DIR:-}" ]; then
        # Instalar desde una copia local: sirve para probar el instalador y
        # para instalar desde un clon sin pasar por una versión publicada.
        paso "Copiando el código de $LARES_SOURCE_DIR"
        cp -a "$LARES_SOURCE_DIR"/. "$DESTINO"/
    else
        paso "Bajando el código"
        curl -fsSL "https://github.com/$REPO/archive/refs/tags/v$VERSION.tar.gz" \
            | tar -xz --strip-components=1 -C "$DESTINO"
    fi
fi

paso "Instalando dependencias de la aplicación"
cd "$DESTINO"
uv sync --no-dev --quiet

ln -sfn "$DESTINO" "$RAIZ/current"
chown -R "$USUARIO:$USUARIO" "$RAIZ"

# --- Arrancar ---------------------------------------------------------------
paso "Instalando los servicios"
install -m 644 "$DESTINO/deploy/native/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload

# Las dos órdenes que va a teclear una persona. Apuntan a `current`, así que
# siguen valiendo después de actualizar.
ln -sf "$RAIZ/current/deploy/native/update.sh" /usr/local/bin/lares-update
ln -sf "$RAIZ/current/deploy/native/lares-manage" /usr/local/bin/lares-manage

paso "Preparando la base y los estáticos"
cd "$RAIZ/current"
set -a; . "$RAIZ/lares.env"; set +a
export DJANGO_SETTINGS_MODULE=lares.settings.prod PYTHONPATH="$RAIZ/current/src"
sudo -u "$USUARIO" --preserve-env .venv/bin/python src/manage.py migrate_locked
sudo -u "$USUARIO" --preserve-env .venv/bin/python src/manage.py collectstatic --noinput >/dev/null

systemctl enable --now lares-web lares-worker lares-beat >/dev/null

paso "Comprobando"
for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/salud >/dev/null 2>&1; then
        echo
        curl -s http://127.0.0.1:8000/salud
        echo
        paso "Listo. Entra en http://$(hostname -I | awk '{print $1}'):8000"
        echo
        paso "Crea el primer usuario:   lares-manage createsuperuser"
        paso "Y para actualizar:        lares-update"
        exit 0
    fi
    sleep 2
done

rojo "No contesta. Mira qué dice:  journalctl -u lares-web -n 50"
exit 1
