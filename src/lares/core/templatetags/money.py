"""Formato de dinero.

Un importe sin separadores ni simbolo no se lee: "410000" obliga a contar
digitos. Y en un sistema multi-moneda, "1,200" sin mas es ambiguo entre pesos y
dolares, que es justo donde un error cuesta caro.

Reglas:

  - separadores segun el idioma de la instalacion (es-MX: 1,234.56)
  - simbolo delante
  - el codigo ISO detras SOLO cuando la moneda no es la del hogar

Lo ultimo importa: nadie quiere leer "MXN" en cada linea de su casa en Mexico,
pero si tienes una cuenta en dolares quieres verlo sin ninguna duda.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.formats import number_format
from django.utils.safestring import mark_safe

register = template.Library()

# Muchas monedas de America Latina usan "$": por eso el codigo ISO no es un
# adorno cuando hay mas de una en juego.
SIMBOLOS = {
    "MXN": "$", "USD": "US$", "EUR": "€", "GBP": "£", "CAD": "CA$",
    "JPY": "¥", "CHF": "CHF ", "BRL": "R$", "ARS": "$", "COP": "$",
    "CLP": "$", "PEN": "S/", "UYU": "$U",
}

SIN_DECIMALES = {"JPY", "CLP", "COP"}


def _formatear(value, currency: str, decimals: int | None, mostrar_iso: bool) -> str:
    try:
        cantidad = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ""

    currency = (currency or "").upper()
    if decimals is None:
        decimals = 0 if currency in SIN_DECIMALES else 2

    cuerpo = number_format(cantidad, decimal_pos=decimals, use_l10n=True,
                           force_grouping=True)
    simbolo = SIMBOLOS.get(currency, "")
    signo = ""
    if cuerpo.startswith("-"):
        signo, cuerpo = "-", cuerpo[1:]

    texto = f"{signo}{simbolo}{cuerpo}"
    if mostrar_iso and currency:
        texto = f"{texto} {currency}"
    return texto


@register.simple_tag(takes_context=True)
def money(context, value, currency=None, decimals=None):
    """`{% money r.current_value r.currency %}` → `$410,000.00`"""
    if value is None or value == "":
        return ""
    hogar = context.get("current_household")
    base = getattr(hogar, "currency", "") or ""
    currency = (currency or base or "").upper()
    return mark_safe(  # noqa: S308 - solo digitos, simbolos y el codigo ISO
        _formatear(value, currency, decimals, mostrar_iso=bool(currency and currency != base))
    )


@register.simple_tag(takes_context=True)
def money0(context, value, currency=None):
    """Sin centavos, para las cifras grandes de resumen donde son ruido."""
    return money(context, value, currency, decimals=0)
