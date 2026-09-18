"""Lo que cuelga de alguien con quien tienes un prestamo."""

from django.urls import reverse

from lares.core.models import Party
from lares.core.registry import RelatedLink
from lares.core.related import _importe

from .models import Loan


def for_party(party) -> list:
    if not isinstance(party, Party):
        return []

    salida = []
    for direccion, etiqueta in (
        (Loan.Direction.LENT, "te debe"),
        (Loan.Direction.BORROWED, "le debes"),
    ):
        prestamos = [
            x for x in Loan.objects.filter(counterpart=party, direction=direccion,
                                           status=Loan.Status.ACTIVE)
            if not x.is_settled
        ]
        if prestamos:
            pendiente = sum(x.outstanding for x in prestamos)
            salida.append(RelatedLink(
                label=etiqueta, count=len(prestamos),
                url=reverse("loans:list"),
                hint=_importe(pendiente, party.household),
            ))
    return salida
