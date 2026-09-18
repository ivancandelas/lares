"""Bases comunes a todos los modelos del dominio."""

from django.db import models

from ..ids import uuid7
from ..scoping import HouseholdManager, HouseholdQuerySet


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Nunca se borra nada: se archiva. Un borrado real destruye el historial
    # y rompe las referencias del grafo. Ver ADR-0005.
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Campos que no vale la pena tipar. NO es un sustituto de modelar bien:
    # si algo se consulta o se filtra, merece una columna.
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class HouseholdScopedModel(TimestampedModel):
    """Todo dato de negocio cuelga de un hogar. Sin excepciones.

    Esta columna existe desde la primera migracion aunque el despliegue sea
    mono-usuario: anadir multi-tenencia despues es una reescritura, anadirla
    ahora es una columna. Ver ADR-0007.
    """

    household = models.ForeignKey(
        "core.Household",
        on_delete=models.CASCADE,
        related_name="%(class)s_set",
        db_index=True,
    )

    objects = HouseholdManager()
    all_objects = models.Manager.from_queryset(HouseholdQuerySet)()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"
