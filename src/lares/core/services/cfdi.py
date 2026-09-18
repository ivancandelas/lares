"""Lectura de CFDI, la factura electronica mexicana.

Es la fuente de mayor valor de todo el sistema y la que ningun producto
internacional tiene. En Mexico cada factura es un XML firmado y estructurado:
RFC del emisor, conceptos, importes, impuestos, UUID fiscal y fecha. No hace
falta OCR ni adivinar nada.

De aqui salen, casi gratis: gastos reales y verificables, altas de activos con
su factura ya asociada, y proveedores con el RFC como identificador canonico.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Cfdi:
    uuid: str = ""
    issued_at: dt.date | None = None
    total: str = ""
    currency: str = "MXN"
    serie: str = ""
    folio: str = ""
    issuer_name: str = ""
    issuer_tax_id: str = ""
    receiver_name: str = ""
    receiver_tax_id: str = ""
    concepts: list = field(default_factory=list)

    @property
    def title(self) -> str:
        emisor = self.issuer_name or self.issuer_tax_id or "emisor desconocido"
        fecha = f" {self.issued_at:%Y-%m-%d}" if self.issued_at else ""
        return f"Factura de {emisor}{fecha}"


def _tag(element) -> str:
    """Nombre sin espacio de nombres: los CFDI cambian el prefijo entre versiones."""
    return element.tag.rsplit("}", 1)[-1]


def _find(root, name: str):
    if _tag(root) == name:
        return root
    for element in root.iter():
        if _tag(element) == name:
            return element
    return None


def parse(data: bytes) -> Cfdi | None:
    """Devuelve el CFDI, o None si el XML no lo es."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if _tag(root) != "Comprobante":
        return None

    cfdi = Cfdi(
        total=root.get("Total") or root.get("total") or "",
        currency=root.get("Moneda") or root.get("moneda") or "MXN",
        serie=root.get("Serie") or "",
        folio=root.get("Folio") or "",
        issued_at=_date(root.get("Fecha") or root.get("fecha")),
    )

    # OJO: un Element sin hijos es falsy en ElementTree. Comparar con None
    # o los datos del emisor se pierden en silencio.
    if (emisor := _find(root, "Emisor")) is not None:
        cfdi.issuer_name = emisor.get("Nombre") or emisor.get("nombre") or ""
        cfdi.issuer_tax_id = emisor.get("Rfc") or emisor.get("rfc") or ""
    if (receptor := _find(root, "Receptor")) is not None:
        cfdi.receiver_name = receptor.get("Nombre") or receptor.get("nombre") or ""
        cfdi.receiver_tax_id = receptor.get("Rfc") or receptor.get("rfc") or ""
    if (timbre := _find(root, "TimbreFiscalDigital")) is not None:
        cfdi.uuid = timbre.get("UUID") or ""

    for element in root.iter():
        if _tag(element) == "Concepto":
            descripcion = element.get("Descripcion") or element.get("descripcion") or ""
            if descripcion:
                cfdi.concepts.append({
                    "description": descripcion,
                    "amount": element.get("Importe") or "",
                })
    return cfdi


def _date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value).date()
    except ValueError:
        return None
