"""Lo que cuelga de un proveedor o de la persona a cuyo nombre esta la cuenta."""

from django.urls import reverse

from lares.core.models import Party
from lares.core.registry import RelatedLink
from lares.core.related import _importe

from .models import Subscription


def for_party(party) -> list:
    if not isinstance(party, Party):
        return []

    salida = []
    vendidas = Subscription.objects.filter(provider=party,
                                           status=Subscription.Status.ACTIVE)
    n = vendidas.count()
    if n:
        anual = sum(s.yearly_cost or 0 for s in vendidas)
        salida.append(RelatedLink(
            label="suscripción" if n == 1 else "suscripciones", count=n,
            url=reverse("subscriptions:list"),
            hint=f"{_importe(anual, party.household)} al año" if anual else "",
        ))

    suyas = Subscription.objects.filter(account_holder=party,
                                        status=Subscription.Status.ACTIVE)
    m = suyas.count()
    if m:
        anual = sum(s.yearly_cost or 0 for s in suyas)
        salida.append(RelatedLink(
            label="cuenta que le pagas" if m == 1 else "cuentas que le pagas",
            count=m, url=reverse("subscriptions:list"),
            hint=f"{_importe(anual, party.household)} al año" if anual else "",
        ))
    return salida
