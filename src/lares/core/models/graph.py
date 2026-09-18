"""Primitiva 3 - Link: el grafo.

Es la pieza central del producto. La poliza no "pertenece" al auto por una FK:
existe una arista (poliza) --asegura--> (auto), con vigencia propia. Esto
permite responder cosas que una FK no puede:

    "que poliza estaba vigente el dia que choque"
    "que cubria el seguro anterior"
    "quien era el propietario antes de la venta"

Las aristas son bitemporales: valid_from/valid_to describen cuando fue cierto
en el mundo real; created_at, cuando lo supimos. Ver ADR-0005.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from ..scoping import HouseholdManager, HouseholdQuerySet
from .base import HouseholdScopedModel


class LinkQuerySet(HouseholdQuerySet):
    def valid_on(self, when):
        """Aristas vigentes en una fecha dada."""
        return self.filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=when),
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=when),
        )

    def role(self, role: str):
        return self.filter(role=role)


class Link(HouseholdScopedModel):
    source_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="links_as_source"
    )
    source_id = models.UUIDField()
    source = GenericForeignKey("source_type", "source_id")

    # Clave de rol registrada por un modulo: "insures", "pays_for",
    # "maintained_by", "enrolled_in", "documents".
    role = models.CharField(max_length=40, db_index=True)

    target_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="links_as_target"
    )
    target_id = models.UUIDField()
    target = GenericForeignKey("target_type", "target_id")

    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    objects = HouseholdManager.from_queryset(LinkQuerySet)()
    all_objects = models.Manager.from_queryset(LinkQuerySet)()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "objects"
        indexes = [
            models.Index(fields=["household", "source_type", "source_id", "role"]),
            models.Index(fields=["household", "target_type", "target_id", "role"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "source_type", "source_id", "role",
                        "target_type", "target_id", "valid_from"],
                name="uniq_link_edge",
            ),
        ]

    def __str__(self):
        return f"{self.source} -[{self.role}]-> {self.target}"
