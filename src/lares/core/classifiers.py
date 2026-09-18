"""Reconocedores del nucleo.

Ninguno crea nada: devuelven una propuesta que la persona confirma. Un
clasificador que escribe en la base por su cuenta convierte el sistema en algo
en lo que no se puede confiar, porque deja de distinguirse lo verificado de lo
adivinado.
"""

from __future__ import annotations

import re

from .registry import Classifier, Proposal
from .services import cfdi as cfdi_service

# Palabras que delatan el tipo de documento. Deliberadamente cortas y en
# minusculas: se comparan contra el nombre del archivo y el texto extraido.
PISTAS = [
    ("passport", "Pasaporte", ("pasaporte", "passport")),
    ("drivers_license", "Licencia de conducir", ("licencia de conducir", "licencia")),
    ("id_card", "Credencial de elector",
     ("credencial para votar", "ine ", "instituto nacional electoral")),
    ("policy", "Póliza de seguro", ("póliza", "poliza", "aseguradora", "cobertura amplia")),
    ("statement", "Estado de cuenta", ("estado de cuenta", "saldo al corte", "pago mínimo")),
    ("deed", "Escritura", ("escritura", "notaría", "notaria")),
    ("invoice", "Factura", ("factura", "cfdi")),
    ("tax", "Predial o impuesto", ("predial", "impuesto", "refrendo", "tenencia")),
    ("utility", "Recibo de servicio", ("recibo", "cfe", "consumo kwh", "agua potable")),
]

FECHA = re.compile(
    r"(?:vence|vigencia|válido hasta|valido hasta|vencimiento)\D{0,20}"
    r"(\d{1,2})[/\-\s](\d{1,2}|\w{3,10})[/\-\s](\d{2,4})",
    re.IGNORECASE,
)


class CfdiClassifier(Classifier):
    """Un CFDI no se adivina: se lee. Por eso va primero y con confianza alta."""

    key = "core.cfdi"
    label = "Factura electrónica (CFDI)"

    def classify(self, item):
        if not item.file:
            return None
        nombre = (item.original_name or "").lower()
        if not (nombre.endswith(".xml") or "xml" in (item.mime_type or "")):
            return None

        with item.file.open("rb") as fh:
            parsed = cfdi_service.parse(fh.read())
        if not parsed:
            return None

        return Proposal(
            label=parsed.title,
            confidence=0.99,           # está firmado por el SAT: no hay duda
            plan={
                "document": {
                    "title": parsed.title,
                    "doc_type": "invoice",
                    "issued_on": parsed.issued_at.isoformat() if parsed.issued_at else None,
                    "amount": parsed.total or None,
                    "currency": parsed.currency,
                },
                "party": {
                    "name": parsed.issuer_name or parsed.issuer_tax_id,
                    "tax_id": parsed.issuer_tax_id,
                    "kind": "organization",
                } if (parsed.issuer_name or parsed.issuer_tax_id) else None,
                "cfdi": {"uuid": parsed.uuid,
                         "concepts": parsed.concepts[:10]},
            },
        )


class KeywordClassifier(Classifier):
    """Lo demás se reconoce por pistas del nombre y del texto.

    Es tosco a propósito. Acierta lo suficiente para ahorrar teclear, y cuando
    falla la persona lo corrige en el mismo formulario: no hay coste.
    """

    key = "core.keywords"
    label = "Pistas del nombre y del texto"

    def classify(self, item):
        aguja = f"{item.original_name or ''}\n{item.text or ''}".lower()
        for doc_type, etiqueta, pistas in PISTAS:
            if any(pista in aguja for pista in pistas):
                return Proposal(
                    label=etiqueta,
                    confidence=0.45,
                    plan={"document": {
                        "title": _titulo(item, etiqueta),
                        "doc_type": doc_type,
                    }},
                )
        return None


def _titulo(item, etiqueta: str) -> str:
    nombre = (item.original_name or "").rsplit(".", 1)[0].replace("_", " ").strip()
    return nombre.capitalize() if len(nombre) > 3 else etiqueta
