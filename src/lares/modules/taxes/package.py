"""El paquete anual para el contador.

Es la salida principal del modulo. Lo que un contador pide cada abril es
siempre lo mismo -las facturas, las retenciones y un resumen de que es cada
cosa- y lo que recibe suele ser una carpeta de Drive sin orden o un correo con
veinte adjuntos.

Aqui sale un ZIP con el resumen en CSV y los archivos que existan, con nombres
que dicen que son. Se arma en memoria y de una vez al ano, asi que no hace
falta nada mas complicado; lo unico que se vigila es no intentar meter medio
disco en RAM.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from decimal import Decimal

from .models import Deduction, Withholding
from .services import summarize

TOPE_BYTES = 200 * 1024 * 1024        # más allá, el ZIP se entrega sin archivos


def _seguro(nombre: str) -> str:
    limpio = re.sub(r"[^\w.\- ]", "_", nombre, flags=re.UNICODE).strip()
    return (limpio or "documento")[:80]


def _csv(filas: list, cabecera: list) -> bytes:
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(cabecera)
    escritor.writerows(filas)
    # BOM: sin el, Excel en Windows parte los acentos.
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _resumen_csv(resumen) -> bytes:
    filas = [
        ["Contribuyente", str(resumen.profile.taxpayer)],
        ["RFC", resumen.profile.rfc],
        ["Régimen", resumen.profile.get_regime_display()],
        ["Ejercicio", resumen.year],
        [],
        ["Ingresos del ejercicio", resumen.income],
    ]
    if resumen.blind_deduction:
        filas.append(["Deducción ciega (35%, art. 115 LISR)",
                      resumen.blind_deduction])
    filas += [
        ["Deducciones personales registradas", resumen.personal],
        ["Deducciones personales que sí cuentan", resumen.personal_allowed],
        ["Deducciones de la actividad", resumen.business],
        ["Base gravable estimada", resumen.base],
        [],
        ["ISR retenido", resumen.withheld_isr],
        ["IVA retenido", resumen.withheld_iva],
        [],
        ["Deducciones por tipo", ""],
    ]
    filas += [[etiqueta, importe] for etiqueta, importe in resumen.by_kind.items()]
    filas += [
        [],
        ["Topes aplicados", ""],
    ]
    for tope in resumen.caps:
        filas.append([tope.label,
                      tope.limit if tope.applied else "no aplicado"])
    filas += [
        [],
        ["AVISO", "Esto es un resumen de lo registrado, no una declaración. "
                  "La base gravable es una estimación; el cálculo del impuesto "
                  "corresponde al SAT o a tu contador."],
    ]
    return _csv(filas, ["Concepto", "Importe"])


def build(household, profile, year: int) -> tuple[str, bytes]:
    """Devuelve (nombre, contenido) del ZIP."""
    resumen = summarize(household, profile, year)

    deducciones = list(
        Deduction.objects.filter(profile=profile, date__year=year)
        .select_related("document", "beneficiary")
    )
    retenciones = list(
        Withholding.objects.filter(profile=profile, date__year=year)
        .select_related("document", "payer")
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("resumen.csv", _resumen_csv(resumen))
        zf.writestr("deducciones.csv", _csv(
            [[d.date, d.get_kind_display(), d.description or "",
              str(d.beneficiary or ""), d.amount,
              _nombre_de(d.document) if d.document else "sin archivo"]
             for d in deducciones],
            ["Fecha", "Tipo", "Concepto", "A nombre de", "Importe", "Archivo"],
        ))
        zf.writestr("retenciones.csv", _csv(
            [[r.date, r.get_kind_display(), str(r.payer or ""), r.amount,
              _nombre_de(r.document) if r.document else "sin archivo"]
             for r in retenciones],
            ["Fecha", "Impuesto", "Quién retuvo", "Importe", "Archivo"],
        ))

        usados = Decimal(0)
        for origen, carpeta in ((deducciones, "deducciones"),
                                (retenciones, "retenciones")):
            for registro in origen:
                documento = registro.document
                if not (documento and documento.file):
                    continue
                if usados + (documento.size_bytes or 0) > TOPE_BYTES:
                    continue
                try:
                    with documento.file.open("rb") as fh:
                        contenido = fh.read()
                except (OSError, ValueError):
                    # Un archivo que ya no esta no puede impedir el paquete:
                    # el CSV sigue diciendo que existio y cual era.
                    continue
                usados += len(contenido)
                zf.writestr(f"{carpeta}/{_nombre_de(documento)}", contenido)

    nombre = f"impuestos-{year}-{_seguro(profile.rfc or str(profile.taxpayer))}.zip"
    return nombre, buffer.getvalue()


def _nombre_de(documento) -> str:
    base = _seguro(documento.title)
    extension = ""
    if documento.file:
        nombre = documento.file.name
        if "." in nombre:
            extension = "." + nombre.rsplit(".", 1)[-1][:8]
    return f"{documento.pk.hex[:8]}-{base}{extension}"
