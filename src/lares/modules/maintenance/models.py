"""Mantenimiento: lo que hay que hacerle a las cosas para que duren.

Dos piezas que conviene no mezclar:

    Plan     lo que toca hacer cada cierto tiempo o cada tantos kilometros
    Trabajo  lo que se hizo de verdad, quien lo hizo y cuanto costo

El plan genera avisos; el trabajo construye el historial. Sin el historial no
se puede responder "¿quien reparo el boiler?" ni "¿cuanto llevo gastado en el
coche?", que son las dos preguntas por las que existe este modulo.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from lares.core.models import HouseholdScopedModel


class MaintenancePlan(HouseholdScopedModel):
    """Lo que toca hacer, cada cuánto."""

    class Basis(models.TextChoices):
        TIME = "time", "Cada cierto tiempo"
        USAGE = "usage", "Cada tantos kilómetros"

    title = models.CharField("qué hay que hacer", max_length=200)
    subject_type = models.ForeignKey(ContentType, on_delete=models.CASCADE,
                                     related_name="maintenance_plans")
    subject_id = models.UUIDField()
    subject = GenericForeignKey("subject_type", "subject_id")

    basis = models.CharField("cada qué", max_length=10, choices=Basis.choices,
                             default=Basis.TIME)
    every_months = models.PositiveSmallIntegerField("cada cuántos meses", null=True,
                                                    blank=True)
    every_km = models.PositiveIntegerField("cada cuántos km", null=True, blank=True)

    last_done_on = models.DateField("última vez", null=True, blank=True)
    estimated_cost = models.DecimalField("coste estimado", max_digits=12,
                                         decimal_places=2, null=True, blank=True)
    preferred_provider = models.ForeignKey(
        "core.Party", verbose_name="quién suele hacerlo", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="maintenance_plans",
    )
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "plan de mantenimiento"
        verbose_name_plural = "planes de mantenimiento"
        indexes = [models.Index(fields=["household", "subject_type", "subject_id"])]

    def __str__(self):
        return f"{self.title} · {self.subject}"

    @property
    def cadence(self) -> str:
        if self.basis == self.Basis.USAGE and self.every_km:
            return f"cada {self.every_km:,} km"
        if self.every_months == 12:
            return "una vez al año"
        if self.every_months:
            return f"cada {self.every_months} meses"
        return "sin periodicidad"


class WorkOrder(HouseholdScopedModel):
    """Lo que se hizo de verdad. Es el historial, no una tarea."""

    title = models.CharField("qué se hizo", max_length=200)
    subject_type = models.ForeignKey(ContentType, on_delete=models.CASCADE,
                                     related_name="work_orders")
    subject_id = models.UUIDField()
    subject = GenericForeignKey("subject_type", "subject_id")

    plan = models.ForeignKey(MaintenancePlan, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="work_orders")
    done_on = models.DateField("cuándo", db_index=True)
    provider = models.ForeignKey(
        "core.Party", verbose_name="quién lo hizo", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="work_done",
    )
    cost = models.DecimalField("cuánto costó", max_digits=12, decimal_places=2,
                               null=True, blank=True)
    currency = models.CharField("moneda", max_length=3, blank=True)
    odometer_km = models.PositiveIntegerField("kilometraje", null=True, blank=True)

    # La garantía del trabajo, no la del objeto: si el boiler vuelve a fallar
    # en tres meses, lo arregla el mismo sin cobrar.
    warranty_until = models.DateField("garantía del trabajo hasta", null=True,
                                      blank=True)
    notes = models.TextField("notas", blank=True)

    class Meta:
        ordering = ["-done_on"]
        verbose_name = "trabajo"
        verbose_name_plural = "trabajos"
        indexes = [
            models.Index(fields=["household", "subject_type", "subject_id", "-done_on"]),
            models.Index(fields=["household", "provider"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.done_on})"
