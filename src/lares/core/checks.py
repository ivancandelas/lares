"""Huecos que solo se ven mirando varios módulos a la vez.

El nucleo no sabe que modulos existen, asi que aqui no se puede comprobar nada
concreto de un coche o de una poliza. Lo que si se puede es mirar lo que todos
aportan por los puntos de extension, y ahi aparecen huecos que ningun modulo
puede detectar solo.
"""

from __future__ import annotations

import re
import unicodedata

from .registry import Check, Finding, registry

RUIDO = {"recibo", "de", "del", "la", "el", "los", "las", "pago", "cuota",
         "mensualidad", "servicio", "y"}


def _palabras(texto: str) -> set:
    """Las palabras que de verdad identifican algo, sin acentos ni relleno."""
    plano = unicodedata.normalize("NFKD", texto.lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return {p for p in re.split(r"[^a-z0-9]+", plano) if p and p not in RUIDO}


class DuplicateRecurring(Check):
    """Una regla escrita a mano que repite algo que ya se lleva solo.

    Es el error mas facil de cometer y el mas dificil de ver: registras el agua
    como servicio del inmueble y, meses despues, programas el recibo del agua
    como regla. Nada falla -salen dos avisos y el gasto del mes sale al doble-
    pero nadie lo nota, porque cada cosa vive en su pantalla.
    """

    key = "core.duplicate_recurring"
    label = "Recurrente duplicado"
    severity = "normal"

    def run(self, household):
        from .models import ObligationRule, Party
        from .views_crud import _ciclo_de

        aportados = registry.recurring_all(household)
        if not aportados:
            return []

        # Los nombres de personas no identifican nada: "clases de piano de
        # Diego" y "iCloud de Diego" comparten a Diego y no son lo mismo.
        nombres = set()
        for persona in Party.objects.filter(kind=Party.Kind.PERSON):
            nombres |= _palabras(persona.name)

        hallazgos = []
        for regla in ObligationRule.objects.filter(is_active=True):
            if not _ciclo_de(regla):
                continue
            propias = _palabras(regla.label) - nombres
            for otro in aportados:
                if not self._mismo(regla, propias, otro, nombres):
                    continue
                hallazgos.append(Finding(
                    check=self.key,
                    title=f"«{regla.label}» parece repetir «{otro.title}»",
                    detail=(f"Lo mismo contado dos veces sale dos veces en lo "
                            f"que te cuesta el mes, y avisa por duplicado. "
                            f"{otro.title} ya se lleva solo: pausa la regla."),
                    severity=self.severity,
                    subject_type="rule", subject_id=regla.pk,
                ))
                break
        return hallazgos

    def _mismo(self, regla, propias: set, otro, nombres: set) -> bool:
        """Conservador a propósito: mejor callar que acusar en falso.

        Dos cosas distintas con el mismo nombre son raras; una alerta falsa en
        una pantalla que existe para detectar huecos le quita el valor a todas
        las demas.
        """
        if otro.source == "core":
            return False
        if regla.counterparty_id and otro.counterparty:
            if regla.counterparty_id == otro.counterparty.pk:
                return True
        ajenas = _palabras(otro.title) - nombres
        return bool(propias) and bool(ajenas) and bool(propias & ajenas)
