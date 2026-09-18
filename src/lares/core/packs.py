"""Packs de jurisdiccion.

Las reglas que cambian por pais, estado y ano no son codigo. Son datos
versionados: el refrendo de Jalisco o la fecha del predial no deberian exigir un
despliegue, y quien viva en otro estado tiene que poder anadir el suyo sin tocar
Python.

Que SI cabe en un pack: cualquier obligacion que dependa de la fecha y, como
mucho, de un atributo del recurso.

Que NO cabe: las reglas que necesitan leer datos del propio objeto con logica
propia -la verificacion segun el ultimo digito de la placa, el servicio segun el
odometro-. Esas viven en su modulo, que es el unico que sabe leerlos. Fingir que
caben en YAML solo mueve el codigo a un sitio peor.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .registry import ObligationProvider, ObligationSpec
from .schedule import next_occurrences

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PackRule:
    id: str
    label: str
    applies_to: str
    schedule: dict
    pack_id: str
    country: str = ""
    subdivision: str = ""
    remind: tuple = (-30, -7, -1)
    severity: str = "normal"
    amount_field: str = ""
    only_if: dict = field(default_factory=dict)
    note: str = ""

    def matches_household(self, household) -> bool:
        if self.country and household.country and self.country != household.country:
            return False
        if self.subdivision and household.subdivision:
            return self.subdivision == household.subdivision
        return True

    def matches_subject(self, subject) -> bool:
        """`only_if` compara atributos simples del recurso.

        Deliberadamente limitado: si una regla necesita más que esto, pertenece
        a un módulo, no a un pack.
        """
        for atributo, esperado in self.only_if.items():
            if getattr(subject, atributo, None) != esperado:
                return False
        return True


def load(directory: Path | None = None) -> list[PackRule]:
    """Lee todos los packs de un directorio. Un pack roto no tumba a los demás."""
    from django.conf import settings

    directory = Path(directory or settings.PACKS_DIR)
    if not directory.is_dir():
        return []

    reglas: list[PackRule] = []
    for ruta in sorted(directory.glob("*.yaml")):
        try:
            datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            logger.exception("El pack %s no es YAML válido", ruta.name)
            continue

        meta = datos.get("meta") or {}
        for cruda in datos.get("rules") or []:
            try:
                reglas.append(PackRule(
                    id=cruda["id"],
                    label=cruda["label"],
                    applies_to=cruda["applies_to"],
                    schedule=cruda.get("schedule") or {},
                    pack_id=meta.get("id", ruta.stem),
                    country=meta.get("country", ""),
                    subdivision=meta.get("subdivision", ""),
                    remind=tuple(cruda.get("remind") or (-30, -7, -1)),
                    severity=cruda.get("severity", "normal"),
                    amount_field=cruda.get("amount_field", ""),
                    only_if=cruda.get("only_if") or {},
                    note=cruda.get("note", ""),
                ))
            except KeyError:
                logger.exception("Regla incompleta en %s: %s", ruta.name, cruda)
    return reglas


class PackProvider(ObligationProvider):
    """Materializa las reglas de los packs para un tipo de recurso."""

    label = "Regla de jurisdicción"

    def __init__(self, applies_to: str, rules: list[PackRule]):
        self.applies_to = applies_to
        self.key = f"packs.{applies_to}"
        self._rules = rules

    def generate(self, subject, on_date: dt.date):
        household = subject.household
        specs = []
        for regla in self._rules:
            if not (regla.matches_household(household) and regla.matches_subject(subject)):
                continue
            for due in next_occurrences(regla.schedule, on_date, count=2):
                specs.append(ObligationSpec(
                    dedupe_key=f"pack:{regla.pack_id}:{regla.id}:{subject.pk}:{due:%Y-%m}",
                    title=_render(regla.label, subject, due),
                    due_on=due,
                    amount=getattr(subject, regla.amount_field, None)
                    if regla.amount_field else None,
                    currency=getattr(subject, "currency", "") or None,
                    severity=regla.severity,
                    remind_offsets=tuple(regla.remind),
                    payload={"pack": regla.pack_id, "rule": regla.id,
                             "note": regla.note},
                ))
        return specs


def _render(plantilla: str, subject, due: dt.date) -> str:
    return plantilla.format(year=due.year, subject=subject, month=due.month)


def register(registry, directory: Path | None = None) -> dict:
    """Registra un proveedor por cada tipo de recurso que mencionen los packs."""
    reglas = load(directory)
    por_tipo: dict[str, list[PackRule]] = {}
    for regla in reglas:
        por_tipo.setdefault(regla.applies_to, []).append(regla)

    for tipo, suyas in por_tipo.items():
        registry.obligations(PackProvider(tipo, suyas))
    return por_tipo
