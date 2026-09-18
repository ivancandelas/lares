"""Polizas de ejemplo, atadas a lo que cubren."""

import datetime as dt

from django.contrib.contenttypes.models import ContentType

from lares.core.models import Link, Party
from lares.core.models.resource import Resource

from .models import Policy


def seed(household) -> str:
    hoy = dt.date.today()
    gnp, _ = Party.objects.get_or_create(
        household=household, name="GNP Seguros",
        defaults={"kind": Party.Kind.ORGANIZATION})

    mazda = Resource.objects.filter(household=household, name="Mazda CX-5").first()
    depto = Resource.objects.filter(
        household=household, name="Departamento en Chapalita").first()

    plan = [
        ("Seguro del Mazda", Policy.Branch.VEHICLE, 410000, 18500,
         hoy + dt.timedelta(days=34), mazda),
        ("Seguro del departamento", Policy.Branch.HOME, 1800000, 9400,
         hoy + dt.timedelta(days=210), depto),
    ]
    for nombre, ramo, cobertura, prima, vence, objetivo in plan:
        policy, creada = Policy.objects.get_or_create(
            household=household, name=nombre,
            defaults=dict(
                kind="policy", branch=ramo, insurer=gnp,
                policy_number=f"GNP-{abs(hash(nombre)) % 100000:05d}",
                coverage_amount=cobertura, deductible=cobertura * 5 // 100,
                premium=prima, premium_cycle=Policy.Cycle.YEARLY,
                starts_on=vence - dt.timedelta(days=365), ends_on=vence,
                currency="MXN",
            ),
        )
        if creada and objetivo:
            concreto = objetivo.as_concrete()
            Link.objects.get_or_create(
                household=household,
                source_type=ContentType.objects.get_for_model(Policy),
                source_id=policy.pk, role="insures",
                target_type=ContentType.objects.get_for_model(concreto.__class__),
                target_id=concreto.pk, valid_from=policy.starts_on,
                defaults={"valid_to": policy.ends_on},
            )
    return f"pólizas: {Policy.objects.count()}"
