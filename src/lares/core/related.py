"""Que cuelga de cada entidad, segun el nucleo.

Entrar en una ficha tiene que servir para algo mas que leer sus campos: es el
punto desde el que se llega a todo lo demas. Si entras en BBVA quieres ver sus
estados de cuenta y cuanto llevas gastado ahi; si entras en Diego, si le
prestaste la guitarra.

Los modulos anaden los suyos con `registry.related(...)`, asi que el nucleo no
tiene que conocerlos.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.urls import reverse

from .models import Account, Document, Entry, Link, Obligation, Party, Posting
from .models.resource import Resource
from .registry import RelatedLink
from .templatetags.money import SIMBOLOS

LENT_TO = "lent_to"


def _importe(cantidad, household) -> str:
    """Un número suelto en una pista no se lee: «4890» frente a «$4,890»."""
    from django.utils.formats import number_format

    simbolo = SIMBOLOS.get((household.currency or "").upper(), "")
    return f"{simbolo}{number_format(cantidad, decimal_pos=0, force_grouping=True)}"


def for_party(party) -> list:
    """Todo lo que cuelga de una persona u organización."""
    if not isinstance(party, Party):
        return []

    salida = []

    movimientos = Entry.objects.filter(counterparty=party)
    n = movimientos.count()
    if n:
        gastado = Posting.objects.filter(
            entry__counterparty=party, account__type=Account.Type.EXPENSE, amount__gt=0
        ).aggregate(t=Sum("amount"))["t"] or 0
        salida.append(RelatedLink(
            label="movimiento" if n == 1 else "movimientos", count=n,
            url=reverse("finance:merchant", args=[party.pk]),
            hint=f"{_importe(gastado, party.household)} gastados" if gastado else "",
        ))

    para = Posting.objects.filter(beneficiary=party, amount__gt=0)
    total_para = para.aggregate(t=Sum("amount"))["t"] or 0
    if total_para:
        salida.append(RelatedLink(
            label="gastado en esta persona", count=para.count(),
            url=reverse("finance:spending"),
            hint=_importe(total_para, party.household),
        ))

    docs = Document.objects.filter(issuer=party).count()
    if docs:
        salida.append(RelatedLink(label="documento" if docs == 1 else "documentos",
                                  count=docs, url=reverse("core:documents")))

    pendientes = Obligation.objects.filter(
        counterparty=party, status=Obligation.Status.PENDING
    ).count()
    if pendientes:
        salida.append(RelatedLink(label="por pagarle", count=pendientes,
                                  url=reverse("core:dashboard")))

    cuentas = Account.objects.filter(institution=party, is_active=True).count()
    if cuentas:
        salida.append(RelatedLink(label="cuenta" if cuentas == 1 else "cuentas",
                                  count=cuentas, url=reverse("finance:accounts")))

    suyos = Resource.objects.filter(owner=party,
                                    status=Resource.Status.ACTIVE).count()
    if suyos:
        salida.append(RelatedLink(label="a su nombre", count=suyos,
                                  url=reverse("core:holdings")))

    prestados = lent_to(party)
    if prestados:
        salida.append(RelatedLink(
            label="cosa que le prestaste" if len(prestados) == 1
            else "cosas que le prestaste",
            count=len(prestados), url=reverse("core:parties"),
            hint=", ".join(r.name for r in prestados[:3]),
        ))
    return salida


def lent_to(party) -> list:
    """Lo que tiene prestado ahora mismo."""
    ids = Link.objects.filter(
        role=LENT_TO,
        target_type=ContentType.objects.get_for_model(Party),
        target_id=party.pk, valid_to__isnull=True,
    ).values_list("source_id", flat=True)
    return list(Resource.objects.filter(pk__in=ids))


def borrower_of(resource):
    """Quién tiene esto ahora, si está prestado."""
    concreto = resource.as_concrete()
    link = Link.objects.filter(
        role=LENT_TO,
        source_type=ContentType.objects.get_for_model(concreto.__class__),
        source_id=concreto.pk, valid_to__isnull=True,
    ).first()
    return link.target if link else None
