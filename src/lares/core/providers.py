"""Proveedores de obligaciones del propio nucleo.

Son dos, y cubren lo que no pertenece a ningun modulo:

  - todo documento con fecha de vencimiento genera su renovacion (DOC-02)
  - toda regla que el usuario cree a mano se materializa igual que las de un
    modulo o un pack (OBL-09)
"""

from __future__ import annotations

import datetime as dt

from .models import ObligationRule
from .registry import ObligationProvider, ObligationSpec
from .schedule import next_occurrences


class DocumentExpiryProvider(ObligationProvider):
    """Pasaporte, INE, licencia, visa, poliza... si vence, hay que renovarlo."""

    key = "core.document_expiry"
    label = "Vencimiento de documento"
    applies_to = "document"

    # Los documentos de identidad avisan con mucha antelacion: renovarlos
    # implica cita previa y a veces meses de espera.
    LONG_LEAD = {"passport", "visa", "drivers_license", "id_card"}

    def generate(self, document, on_date: dt.date):
        if not document.expires_on:
            return []
        offsets = (-270, -180, -90, -30, -7) if document.doc_type in self.LONG_LEAD \
            else (-60, -30, -7, -1)
        return [ObligationSpec(
            dedupe_key=f"document:{document.pk}:expiry:{document.expires_on:%Y-%m-%d}",
            title=f"Renovar {document.title}",
            due_on=document.expires_on,
            severity="high" if document.doc_type in self.LONG_LEAD else "normal",
            amount=document.amount,
            currency=document.currency or None,
            remind_offsets=offsets,
            payload={"doc_type": document.doc_type},
        )]


class UserRuleProvider(ObligationProvider):
    """Reglas que el usuario define a mano, con el mismo motor que las demas."""

    key = "core.user_rule"
    label = "Regla propia"
    applies_to = "household"

    def generate(self, household, on_date: dt.date):
        specs = []
        for rule in ObligationRule.objects.filter(is_active=True):
            for due in next_occurrences(rule.schedule, on_date, count=2):
                specs.append(ObligationSpec(
                    dedupe_key=f"rule:{rule.pk}:{due:%Y-%m-%d}",
                    title=rule.label,
                    due_on=due,
                    amount=rule.amount,
                    currency=rule.currency or None,
                    remind_offsets=tuple(rule.remind_offsets or (-30, -7, -1)),
                    payload={"rule": str(rule.pk)},
                ))
        return specs
