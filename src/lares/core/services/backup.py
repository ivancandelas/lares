"""Copias de seguridad cifradas.

Un export sin cifrar contiene el patrimonio entero de una familia y sus cuentas
de acceso: guardarlo en un disco externo o en la nube sin cifrar convierte la
copia en el punto mas debil de todo el sistema.

Formato del archivo:

    LARESBK1                 8 bytes, marca de formato
    <salt>                  16 bytes, distinto en cada copia
    <token Fernet>          el .zip del export, cifrado y autenticado

La clave se deriva con scrypt, que esta pensado para ser costoso de forzar por
fuerza bruta. La frase nunca se guarda ni viaja en la linea de comandos.

Limitacion conocida: se cifra en memoria. A escala de un hogar (megabytes) no
importa; si algun dia hay gigabytes de escaneos, habra que cifrar por bloques.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import portability

MAGIC = b"LARESBK1"
SALT_BYTES = 16
SCRYPT_N = 2 ** 15


class BadPassphrase(Exception):
    """La frase no abre el archivo, o el archivo esta alterado."""


def _key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def backup_household(household, destination: Path, passphrase: str) -> Path:
    if not passphrase:
        raise ValueError("Hace falta una frase de paso para cifrar la copia.")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        plano = portability.export_household(household, Path(tmp) / "export.zip")
        salt = os.urandom(SALT_BYTES)
        token = Fernet(_key(passphrase, salt)).encrypt(plano.read_bytes())

    destination.write_bytes(MAGIC + salt + token)
    return destination


def restore_household(source: Path, passphrase: str) -> dict:
    source = Path(source)
    contenido = source.read_bytes()

    if not contenido.startswith(MAGIC):
        raise ValueError(f"{source.name} no es una copia de Lares.")

    salt = contenido[len(MAGIC):len(MAGIC) + SALT_BYTES]
    token = contenido[len(MAGIC) + SALT_BYTES:]
    try:
        plano = Fernet(_key(passphrase, salt)).decrypt(token)
    except InvalidToken as exc:
        raise BadPassphrase(
            "La frase no abre esta copia, o el archivo se alteró."
        ) from exc

    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "export.zip"
        ruta.write_bytes(plano)
        return portability.import_household(ruta)
