"""Lectura de estados de cuenta.

Tres formatos, por orden de fiabilidad:

    OFX   estructurado y con identificador propio de cada movimiento
    CSV   filas y columnas, pero cada banco pone las suyas
    PDF   el ultimo recurso, y el mas fragil

Aqui estan los dos primeros. El PDF depende de plantillas por banco y se hace
cuando haga falta.

La regla que sostiene todo esto: **importar dos veces el mismo archivo no debe
crear nada dos veces**. Un libro con movimientos duplicados no se puede
conciliar, y entonces deja de servir para lo unico que sirve un libro.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

FORMATOS_FECHA = ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%d-%m-%Y",
                  "%Y/%m/%d", "%d.%m.%Y"]


@dataclass
class Movement:
    date: dt.date
    description: str
    amount: Decimal          # positivo entra, negativo sale
    external_ref: str = ""
    balance: Decimal | None = None
    raw: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Identidad de un movimiento cuando el banco no da ninguna.

        Fecha, importe y descripcion normalizada. Dos cargos identicos el mismo
        dia colisionan a proposito: son indistinguibles tambien en el papel, y
        es mejor pedirselo a la persona que inventarse una diferencia.
        """
        if self.external_ref:
            return self.external_ref
        limpio = re.sub(r"\s+", " ", self.description.strip().lower())
        crudo = f"{self.date:%Y-%m-%d}|{self.amount}|{limpio}"
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:32]


def parse_date(valor: str) -> dt.date | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    if len(valor) >= 8 and valor[:8].isdigit():
        try:
            return dt.datetime.strptime(valor[:8], "%Y%m%d").date()
        except ValueError:
            pass
    for formato in FORMATOS_FECHA:
        try:
            return dt.datetime.strptime(valor, formato).date()
        except ValueError:
            continue
    return None


def parse_amount(valor: str) -> Decimal | None:
    """Acepta 1,234.56 y 1.234,56, con o sin simbolo, y (123) como negativo."""
    texto = (valor or "").strip()
    if not texto:
        return None

    negativo = texto.startswith("(") and texto.endswith(")")
    texto = re.sub(r"[^\d,.\-]", "", texto.strip("()"))
    if not texto:
        return None

    if "," in texto and "." in texto:
        # El separador decimal es el que aparece más a la derecha.
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif texto.count(",") == 1 and len(texto.split(",")[1]) in (1, 2):
        texto = texto.replace(",", ".")
    else:
        texto = texto.replace(",", "")

    try:
        cantidad = Decimal(texto)
    except InvalidOperation:
        return None
    return -cantidad if negativo else cantidad


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

# Nombres que usan los bancos para lo mismo. No es exhaustivo ni pretende serlo:
# lo que no se adivine lo elige la persona en un desplegable.
PISTAS = {
    "date": ["fecha", "fecha de operacion", "fecha operación", "date",
             "fecha oper", "f. operacion"],
    "description": ["descripcion", "descripción", "concepto", "detalle",
                    "description", "memo", "referencia"],
    "amount": ["importe", "monto", "amount", "cantidad"],
    "debit": ["cargo", "cargos", "debito", "débito", "retiro", "debit"],
    "credit": ["abono", "abonos", "credito", "crédito", "deposito", "depósito",
               "credit"],
    "balance": ["saldo", "balance"],
}


def sniff_columns(cabeceras: list[str]) -> dict:
    """Adivina qué columna es cuál. Lo que falle lo corrige la persona."""
    mapa = {}
    normalizadas = [(i, (c or "").strip().lower()) for i, c in enumerate(cabeceras)]
    for campo, pistas in PISTAS.items():
        for indice, nombre in normalizadas:
            if nombre in pistas or any(nombre.startswith(p) for p in pistas):
                mapa[campo] = indice
                break
    return mapa


def read_csv(contenido: bytes, mapping: dict | None = None) -> tuple:
    """Devuelve (movimientos, cabeceras, mapeo usado)."""
    texto = _decodificar(contenido)
    try:
        dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
    except csv.Error:
        dialecto = csv.excel

    filas = list(csv.reader(io.StringIO(texto), dialecto))
    filas = [f for f in filas if any(c.strip() for c in f)]
    if not filas:
        return [], [], {}

    # La cabecera es la primera fila que no parece un movimiento.
    cabeceras = filas[0]
    cuerpo = filas[1:]
    mapa = mapping or sniff_columns(cabeceras)

    movimientos = []
    for fila in cuerpo:
        mov = _fila_a_movimiento(fila, mapa, cabeceras)
        if mov:
            movimientos.append(mov)
    return movimientos, cabeceras, mapa


def _fila_a_movimiento(fila, mapa, cabeceras) -> Movement | None:
    def celda(campo):
        indice = mapa.get(campo)
        if indice is None or indice >= len(fila):
            return ""
        return fila[indice]

    fecha = parse_date(celda("date"))
    if not fecha:
        return None

    importe = parse_amount(celda("amount"))
    if importe is None:
        # Muchos bancos separan cargo y abono en dos columnas.
        cargo = parse_amount(celda("debit")) or Decimal(0)
        abono = parse_amount(celda("credit")) or Decimal(0)
        if not (cargo or abono):
            return None
        importe = abono - abs(cargo)

    return Movement(
        date=fecha,
        description=(celda("description") or "Movimiento").strip()[:300],
        amount=importe,
        balance=parse_amount(celda("balance")),
        raw=dict(zip(cabeceras, fila, strict=False)),
    )


def _decodificar(contenido: bytes) -> str:
    for codificacion in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# OFX
# ---------------------------------------------------------------------------

ETIQUETA = re.compile(r"<([A-Z0-9.]+)>([^<\r\n]*)", re.IGNORECASE)


def read_ofx(contenido: bytes) -> list:
    """Lee OFX 1.x (SGML) y 2.x (XML) con el mismo recorrido.

    No se usa un parser de XML porque el OFX 1.x no lo es: no cierra etiquetas.
    Recorrer las marcas a mano es mas corto y aguanta los dos.
    """
    texto = _decodificar(contenido)
    if "<STMTTRN>" not in texto.upper():
        return []

    movimientos = []
    for bloque in re.split(r"<STMTTRN>", texto, flags=re.IGNORECASE)[1:]:
        cuerpo = re.split(r"</STMTTRN>", bloque, flags=re.IGNORECASE)[0]
        campos = {}
        for etiqueta, valor in ETIQUETA.findall(cuerpo):
            campos.setdefault(etiqueta.upper(), valor.strip())

        fecha = parse_date(campos.get("DTPOSTED", ""))
        importe = parse_amount(campos.get("TRNAMT", ""))
        if not fecha or importe is None:
            continue

        descripcion = (campos.get("NAME") or campos.get("MEMO")
                       or campos.get("TRNTYPE") or "Movimiento")
        movimientos.append(Movement(
            date=fecha,
            description=descripcion.strip()[:300],
            amount=importe,
            # FITID es el identificador que da el propio banco: cuando existe,
            # deduplicar deja de ser una heuristica.
            external_ref=campos.get("FITID", "")[:120],
            raw=campos,
        ))
    return movimientos


def read(contenido: bytes, nombre: str = "", mapping: dict | None = None) -> tuple:
    """Elige el lector por el contenido, no por la extensión."""
    cabeza = _decodificar(contenido[:2048]).upper()
    if "OFXHEADER" in cabeza or "<OFX>" in cabeza or "<STMTTRN>" in cabeza:
        return read_ofx(contenido), [], {}
    return read_csv(contenido, mapping)
