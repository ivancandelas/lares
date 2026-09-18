"""Huecos del inventario."""

import datetime as dt

from django.contrib.contenttypes.models import ContentType

from lares.core.models import Link
from lares.core.registry import Check, Finding

from .models import Belonging

# Cada cuánto conviene confirmar que algo sigue donde dice.
REVISION_MESES = 12


def _documentados() -> set:
    ctype = ContentType.objects.get_for_model(Belonging)
    return set(
        Link.objects.filter(role="documents", target_type=ctype)
        .values_list("target_id", flat=True)
    )


class ValuableWithoutInvoice(Check):
    key = "belongings.no_invoice"
    label = "Objeto de valor sin factura"
    severity = "high"

    def run(self, household):
        documentados = _documentados()
        return [
            Finding(
                check=self.key,
                title=f"{b.name} no tiene factura ni documentos",
                detail="Sin factura no se reclama a un seguro ni se hace valer una garantía.",
                severity=self.severity,
                subject_type="belonging",
                subject_id=b.pk,
            )
            for b in Belonging.objects.filter(status=Belonging.Status.ACTIVE)
            if b.is_valuable and b.pk not in documentados
        ]


class WarrantyWithoutProof(Check):
    key = "belongings.warranty_no_proof"
    label = "Garantía sin comprobante"
    severity = "normal"

    def run(self, household):
        hoy = dt.date.today()
        documentados = _documentados()
        return [
            Finding(
                check=self.key,
                title=f"{b.name} está en garantía pero no tienes el comprobante",
                detail=f"Vence el {b.warranty_until:%d/%m/%Y}. Sin factura no te la aplican.",
                severity=self.severity,
                subject_type="belonging",
                subject_id=b.pk,
            )
            for b in Belonging.objects.filter(
                status=Belonging.Status.ACTIVE, warranty_until__gte=hoy
            )
            if b.pk not in documentados
        ]


class StaleValuable(Check):
    """«¿Sigues teniendo esto?»

    Es lo que evita que el inventario envejezca hasta volverse ficción, que es
    el destino de todos los inventarios domésticos.
    """

    key = "belongings.stale"
    label = "Objeto sin comprobar hace tiempo"
    severity = "low"

    def run(self, household):
        limite = dt.date.today() - dt.timedelta(days=REVISION_MESES * 30)
        pendientes = [
            b for b in Belonging.objects.filter(status=Belonging.Status.ACTIVE)
            if b.is_valuable and (b.verified_on or b.created_at.date()) < limite
        ]
        if not pendientes:
            return []
        return [Finding(
            check=self.key,
            title=f"Hace más de un año que no compruebas {len(pendientes)} objeto(s) de valor",
            detail=", ".join(b.name for b in pendientes[:5]),
            severity=self.severity,
        )]
