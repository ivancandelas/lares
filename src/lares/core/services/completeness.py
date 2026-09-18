"""Que tan completo esta el hogar, y que conviene hacer ahora.

La contracara de la ingesta. El sistema no solo debe avisar de lo que sabe:
debe decir que le falta. "No tengo avisos" y "no tengo datos" se parecen
demasiado en pantalla, y confundirlos es justo el punto ciego del producto.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Account, Document, Party, Resource
from ..scoping import use_household
from .checks import run_all


@dataclass(frozen=True)
class Step:
    label: str
    done: bool
    url_name: str
    arg: str | None = None


def assess(household) -> dict:
    with use_household(household):
        pasos = [
            Step("Registrar quién eres", Party.objects.filter(is_self=True).exists(),
                 "core:party-new"),
            Step("Añadir algo que tengas", Resource.objects.exists(), "core:add"),
            Step("Guardar un documento", Document.objects.exists(), "core:document-new"),
            Step("Anotar un vencimiento",
                 Document.objects.filter(expires_on__isnull=False).exists(),
                 "core:document-new"),
            Step("Registrar una cuenta o tarjeta", Account.objects.exists(),
                 "core:account-new"),
            Step("Programar un pago recurrente",
                 Resource.objects.none().exists() or _tiene_reglas(), "core:rule-new"),
        ]
        huecos = run_all(household)

    hechos = sum(1 for p in pasos if p.done)
    # Los huecos pesan: tener datos a medias no es estar completo.
    penalizacion = min(len(huecos), 6) * 4
    score = max(0, round(hechos / len(pasos) * 100) - penalizacion)

    return {
        "score": score,
        "steps": pasos,
        "pending": [p for p in pasos if not p.done],
        "gaps": huecos,
    }


def _tiene_reglas() -> bool:
    from ..models import ObligationRule

    return ObligationRule.objects.filter(is_active=True).exists()
