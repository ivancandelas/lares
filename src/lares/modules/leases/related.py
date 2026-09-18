"""Lo que cuelga de un inquilino o de un arrendador."""

from django.urls import reverse

from lares.core.models import Party
from lares.core.registry import RelatedLink
from lares.core.related import _importe

from .models import Lease


def for_party(party) -> list:
    if not isinstance(party, Party):
        return []

    salida = []
    for direccion, etiqueta in (
        (Lease.Direction.LANDLORD, "te renta"),
        (Lease.Direction.TENANT, "le rentas"),
    ):
        contratos = [x for x in Lease.objects.filter(
            counterpart=party, direction=direccion, status=Lease.Status.ACTIVE)]
        if contratos:
            atrasos = sum(len(x.overdue_payments) for x in contratos)
            pista = _importe(sum(x.rent_amount for x in contratos),
                             party.household) + " al mes"
            if atrasos:
                pista += f", {atrasos} {'mes' if atrasos == 1 else 'meses'} sin pagar"
            salida.append(RelatedLink(
                label=etiqueta, count=len(contratos),
                url=reverse("leases:list"), hint=pista,
            ))
    return salida
