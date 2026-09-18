"""Cifrado de los secretos de los conectores.

Un token de Paperless o la contrasena de un buzon IMAP no son datos del hogar:
son llaves para entrar en otro sitio. Guardarlas en claro convierte la base de
datos en un llavero.

Limitacion honesta: la clave se deriva de SECRET_KEY, asi que quien tenga la
base de datos *y* la configuracion puede descifrarlas. Protege contra un volcado
de la base, no contra alguien que ya esta dentro del servidor. Para el modo SaaS
habria que mover esto a un gestor de claves externo.

Nunca se guardan aqui credenciales bancarias. Para eso no hay excepcion.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

_PREFIX = "enc:"


def _key() -> bytes:
    digest = hashlib.blake2b(
        settings.SECRET_KEY.encode("utf-8"), salt=b"lares-secrets", digest_size=32
    ).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _PREFIX + Fernet(_key()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        # Valor antiguo sin cifrar: se devuelve tal cual para no perderlo.
        return value
    try:
        return Fernet(_key()).decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        # Cambió SECRET_KEY: el secreto es irrecuperable y hay que volver a pedirlo.
        return ""
