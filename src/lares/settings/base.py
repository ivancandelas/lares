"""Configuracion base de Lares.

Todo lo especifico del producto se lee del entorno con el prefijo LARES_.
Ver .env.example.
"""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parents[2]      # .../src
PROJECT_ROOT = BASE_DIR.parent                      # raiz del repo

env = environ.Env()
environ.Env.read_env(PROJECT_ROOT / ".env")

# --- Identidad del producto -------------------------------------------------
# Unico lugar donde vive el nombre visible. `make rename` cambia el paquete.
PRODUCT_NAME = "Lares"
PRODUCT_TAGLINE = "Tu hogar, administrado."

# --- Nucleo -----------------------------------------------------------------
SECRET_KEY = env("LARES_SECRET_KEY", default="dev-inseguro-no-usar-en-produccion")
DEBUG = env.bool("LARES_DEBUG", default=False)
ALLOWED_HOSTS = env.list("LARES_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --- Modo de tenencia -------------------------------------------------------
# "single": self-hosted, un solo hogar. "multi": SaaS.
# El codigo es identico en ambos; esto solo controla UI de cuenta, registro
# publico y si se exige RLS. Ver docs/04-tenancy-and-saas.md
TENANCY_MODE = env("LARES_TENANCY_MODE", default="single")

# --- Aplicaciones -----------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

CORE_APPS = [
    "lares.core",
]

# Modulos instalables (addons). Anadir aqui o via LARES_MODULES.
# El registro resuelve dependencias y orden; ver lares/core/registry.py
LARES_MODULES = env.list(
    "LARES_MODULES",
    default=[
        "lares.modules.belongings.apps.BelongingsModule",
        "lares.modules.finance.apps.FinanceModule",
        "lares.modules.property.apps.PropertyModule",
        "lares.modules.tasks.apps.TasksModule",
        "lares.modules.vehicles.apps.VehiclesModule",
    ],
)

INSTALLED_APPS = DJANGO_APPS + CORE_APPS + LARES_MODULES

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Todo exige sesion, tambien en self-hosted: la instalacion puede estar
    # expuesta y aqui vive el patrimonio entero de una familia.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Fija el hogar activo para toda la peticion. Debe ir despues de Auth.
    "lares.core.middleware.HouseholdMiddleware",
]

ROOT_URLCONF = "lares.urls"
WSGI_APPLICATION = "lares.wsgi.application"
ASGI_APPLICATION = "lares.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "lares" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "lares.core.context_processors.product",
            ],
        },
    },
]

# --- Datos ------------------------------------------------------------------
DATABASES = {
    "default": env.db_url(
        "LARES_DATABASE_URL",
        default="postgres://lares:lares@localhost:5432/lares",
    ),
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "core.User"

LOGIN_URL = "/entrar/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/entrar/"

# --- Correo (avisos de obligaciones) ---------------------------------------
vars().update(env.email_url("LARES_EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("LARES_FROM_EMAIL", default="lares@localhost")

# --- Cola de trabajos -------------------------------------------------------
CELERY_BROKER_URL = env("LARES_REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_ALWAYS_EAGER = False

# Calendario de las tareas de fondo. Todas son idempotentes, así que se pueden
# reintentar, adelantar o repetir sin que al usuario le llegue nada por
# duplicado. Sin esto, el servicio `beat` arranca y no hace absolutamente nada.
CELERY_BEAT_SCHEDULE = {
    "materializar-obligaciones": {
        "task": "lares.core.tasks.materialize_obligations",
        "schedule": crontab(hour=3, minute=10),
    },
    "enviar-recordatorios": {
        "task": "lares.core.tasks.send_reminders",
        # A las 7 y no de madrugada: un aviso se lee cuando empieza el día.
        "schedule": crontab(hour=7, minute=0),
    },
    "detectar-huecos": {
        "task": "lares.core.tasks.run_checks",
        "schedule": crontab(hour=3, minute=40),
    },
    "traer-de-los-conectores": {
        "task": "lares.core.tasks.poll_connectors",
        "schedule": crontab(minute="*/15"),
    },
}

# --- Internacionalizacion ---------------------------------------------------
LANGUAGE_CODE = env("LARES_LANGUAGE_CODE", default="es-mx")
TIME_ZONE = env("LARES_TIME_ZONE", default="America/Mexico_City")
USE_I18N = True
USE_TZ = True

DEFAULT_COUNTRY = env("LARES_DEFAULT_COUNTRY", default="MX")
DEFAULT_SUBDIVISION = env("LARES_DEFAULT_SUBDIVISION", default="MX-JAL")
DEFAULT_CURRENCY = env("LARES_DEFAULT_CURRENCY", default="MXN")

# --- Archivos ---------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = PROJECT_ROOT / "staticfiles"
MEDIA_URL = "media/"
# Vacío o sin definir: carpeta del proyecto. En Docker se pasa /data/media.
MEDIA_ROOT = env("LARES_MEDIA_ROOT", default="") or str(PROJECT_ROOT / "data" / "media")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Paquetes de obligaciones por jurisdiccion ------------------------------
PACKS_DIR = PROJECT_ROOT / "packs"
