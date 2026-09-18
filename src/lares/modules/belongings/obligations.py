"""Garantias: lo que mas se pierde por no enterarse a tiempo."""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec


class WarrantyExpiryProvider(ObligationProvider):
    """Avisa antes de que caduque la garantía, no el día que caduca.

    Una garantía sirve si te acuerdas de usarla mientras aún vale. Treinta días
    de margen es lo mínimo para llevar algo a revisar sin prisas.
    """

    key = "belongings.warranty"
    label = "Garantía por vencer"
    applies_to = "belonging"

    def generate(self, belonging, on_date: dt.date):
        if not belonging.warranty_until or belonging.warranty_until < on_date:
            return []
        return [ObligationSpec(
            dedupe_key=f"belonging:{belonging.pk}:warranty:{belonging.warranty_until:%Y-%m-%d}",
            title=f"Vence la garantía de {belonging.name}",
            due_on=belonging.warranty_until,
            severity="normal",
            remind_offsets=(-60, -30, -7),
            payload={"note": belonging.warranty_note},
        )]
