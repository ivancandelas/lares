from .base import *  # noqa: F403

DEBUG = False

# --- ¿Hay TLS delante? ------------------------------------------------------
# Lo normal es que sí: un proxy que termina HTTPS y habla con Lares por dentro.
# Pero una instalación en la LAN de casa -un LXC al que se entra por IP- no
# tiene ninguno, y entonces exigir HTTPS deja la aplicación inservible: todo
# responde 301 hacia una dirección que no existe.
#
# Por eso se puede apagar, sabiendo lo que se pierde: sin TLS, las cookies de
# sesión y el token CSRF viajan en claro por la red local. Vale para una casa
# con una red en la que confías; no vale para nada que se asome a internet.
HTTPS = env.bool("LARES_HTTPS", default=True)  # noqa: F405

SECURE_SSL_REDIRECT = HTTPS
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
SECURE_HSTS_SECONDS = 31536000 if HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Con proxy delante hay que decirle a Django desde qué dominio se le llama, o
# rechaza los formularios con un 403 que no explica nada.
CSRF_TRUSTED_ORIGINS = env.list("LARES_CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405
# SAMEORIGIN, no DENY: el visor de documentos incrusta archivos propios.
X_FRAME_OPTIONS = "SAMEORIGIN"

# --- Para que el healthcheck no mienta -------------------------------------
# Dos ajustes de producción se lo cargaban sin que nada avisara:
#
#   1. `SECURE_SSL_REDIRECT` convierte la comprobación en un 301, y `curl -f`
#      da por bueno un 301: el contenedor saldría "sano" aunque la aplicación
#      estuviera muerta.
#   2. La comprobación entra por 127.0.0.1, así que si alguien pone su dominio
#      en LARES_ALLOWED_HOSTS, Django contesta 400 y el contenedor no vuelve a
#      estar sano nunca.
SECURE_REDIRECT_EXEMPT = [r"^salud"]
ALLOWED_HOSTS = list(dict.fromkeys(
    [*ALLOWED_HOSTS, "127.0.0.1", "localhost"]  # noqa: F405
))
