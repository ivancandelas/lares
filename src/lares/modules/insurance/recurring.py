"""La prima de cada póliza viva."""

from django.urls import reverse

from lares.core.registry import Recurring

from .models import Policy


def recurring(household) -> list:
    return [
        Recurring(
            title=poliza.name,
            amount=poliza.premium,
            cycle=poliza.premium_cycle,
            currency=poliza.currency,
            counterparty=poliza.insurer,
            url=reverse("core:resource-detail", args=[poliza.pk]),
            source="insurance",
            note=poliza.get_branch_display(),
        )
        for poliza in Policy.objects.filter(status=Policy.Status.ACTIVE)
        if poliza.premium
    ]
