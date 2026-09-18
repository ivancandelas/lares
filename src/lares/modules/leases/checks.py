"""Lo que se pierde de vista en un arrendamiento."""

import datetime as dt

from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q

from lares.core.models import Link
from lares.core.registry import Check, Finding

from .models import Lease, RentPayment


def _meses(cuantos: int) -> str:
    return "mes" if cuantos == 1 else "meses"


class LateRent(Check):
    """Un mes sin cobrar es un mes que ya no se recupera."""

    key = "leases.late"
    label = "Renta sin pagar"
    severity = "high"

    def run(self, household):
        hoy = dt.date.today()
        atrasos = {}
        # No basta con los que no tienen fecha de pago: un mes abonado a
        # medias sigue debiendo, y es el que se escapa sin que nadie lo note.
        candidatos = RentPayment.objects.filter(due_on__lt=hoy).filter(
            Q(paid_on__isnull=True) | Q(amount_paid__lt=F("amount"))
        )
        for pago in candidatos:
            if pago.is_late(hoy):
                atrasos.setdefault(pago.lease_id, []).append(pago)

        hallazgos = []
        for lease in Lease.objects.filter(pk__in=atrasos):
            pendientes = sorted(atrasos[lease.pk], key=lambda p: p.due_on)
            dias = pendientes[0].days_late(hoy)
            total = sum(p.shortfall for p in pendientes)
            quien = f" {lease.counterpart}" if lease.counterpart else ""
            verbo = "sin cobrar" if lease.is_landlord else "sin pagar"
            hallazgos.append(Finding(
                check=self.key,
                title=(f"{len(pendientes)} {_meses(len(pendientes))} {verbo} "
                       f"de {lease.property_ref.name}"),
                detail=(f"{total:,.0f} pendientes, el más viejo lleva {dias} días"
                        f"{quien}."),
                severity="critical" if dias > 30 else self.severity,
                subject_type="lease", subject_id=lease.pk,
            ))
        return hallazgos


class RentedWithoutLease(Check):
    """Un inmueble marcado «en renta» sin contrato registrado.

    Es el hueco que hace que no se cobre, no se avise del fin y no se sepa
    cuanto renta de verdad.
    """

    key = "leases.no_lease"
    label = "Inmueble en renta sin contrato"
    severity = "high"

    def run(self, household):
        from lares.modules.property.models import Property

        con_contrato = set(
            Lease.objects.filter(status=Lease.Status.ACTIVE)
            .values_list("property_ref_id", flat=True)
        )
        return [
            Finding(
                check=self.key,
                title=f"{p.name} está en renta pero no tiene contrato registrado",
                detail="Sin él no hay cobro que avise, ni fin de contrato, "
                       "ni forma de saber cuánto renta.",
                severity=self.severity,
                subject_type="property", subject_id=p.pk,
            )
            for p in Property.objects.filter(
                status=Property.Status.ACTIVE,
                use__in=[Property.Use.RENTED_OUT],
            )
            if p.pk not in con_contrato
        ]


class LeaseWithoutDocument(Check):
    key = "leases.no_document"
    label = "Contrato sin el papel firmado"
    severity = "normal"

    def run(self, household):
        ctype = ContentType.objects.get_for_model(Lease)
        documentados = set(
            Link.objects.filter(role="documents", target_type=ctype)
            .values_list("target_id", flat=True)
        )
        return [
            Finding(
                check=self.key,
                title=f"{lease.name} no tiene el contrato escaneado",
                detail="Cuando haya que reclamar algo, lo que vale es el papel.",
                severity=self.severity,
                subject_type="lease", subject_id=lease.pk,
            )
            for lease in Lease.objects.filter(status=Lease.Status.ACTIVE)
            if lease.pk not in documentados
        ]


class DepositPending(Check):
    """El depósito que dejaste y nadie ha devuelto al acabar el contrato."""

    key = "leases.deposit"
    label = "Depósito por recuperar"
    severity = "high"

    def run(self, household):
        hoy = dt.date.today()
        return [
            Finding(
                check=self.key,
                title=f"Te deben {lease.deposit_pending:,.0f} de depósito",
                detail=(f"El contrato de {lease.property_ref.name} acabó el "
                        f"{lease.ends_on:%d/%m/%Y} y el depósito sigue sin devolver."),
                severity=self.severity,
                subject_type="lease", subject_id=lease.pk,
            )
            for lease in Lease.objects.filter(direction=Lease.Direction.TENANT)
            if (lease.ends_on and lease.ends_on < hoy and lease.deposit_pending)
        ]


class NoDeposit(Check):
    """Un contrato sin el deposito anotado.

    El deposito es de las cantidades mas grandes que se mueven en un
    arrendamiento y la mas facil de olvidar: se entrega una vez, al principio, y
    no vuelve a aparecer en ningun recibo hasta que toca reclamarlo. Si no
    quedo escrito aqui, al final depende de que alguien se acuerde.
    """

    key = "leases.no_deposit"
    label = "Contrato sin depósito anotado"
    severity = "normal"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{lease.name} no tiene el depósito anotado",
                detail=("Si dejaste depósito, anótalo: es lo que se reclama al "
                        "salir y no aparece en ningún recibo mensual."),
                severity=self.severity,
                subject_type="lease", subject_id=lease.pk,
            )
            for lease in Lease.objects.filter(status=Lease.Status.ACTIVE,
                                              deposit_amount__isnull=True)
            if lease.is_live
        ]


class NoInventory(Check):
    """Sin acta de entrega, recuperar el depósito depende de la memoria."""

    key = "leases.no_inventory"
    label = "Contrato sin acta de entrega"
    severity = "low"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{lease.name} no tiene acta de entrega",
                detail="Unas fotos del estado al entrar valen más que cualquier "
                       "discusión al salir.",
                severity=self.severity,
                subject_type="lease", subject_id=lease.pk,
            )
            for lease in Lease.objects.filter(status=Lease.Status.ACTIVE,
                                              direction=Lease.Direction.TENANT)
            if lease.is_live and not lease.description
        ]
