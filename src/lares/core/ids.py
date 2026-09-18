"""Identificadores UUIDv7.

Se usan como clave primaria en todo el sistema. Razones (ver ADR-0004):
  - Ordenables por tiempo: los indices no se fragmentan como con UUIDv4.
  - Globalmente unicos: exportar, importar y fusionar instancias no colisiona.
  - No revelan volumen ni permiten enumeracion, a diferencia de un autoincremento.

Implementacion local para no anadir una dependencia por 20 lineas.
Formato RFC 9562: 48 bits de timestamp ms | version 7 | 74 bits aleatorios.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")

    value = ts_ms << 80
    value |= 0x7 << 76                                  # version
    value |= ((rand >> 62) & ((1 << 12) - 1)) << 64     # rand_a
    value |= 0b10 << 62                                 # variant
    value |= rand & ((1 << 62) - 1)                     # rand_b
    return uuid.UUID(int=value)
