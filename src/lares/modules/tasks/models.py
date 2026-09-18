from django.db import models

from lares.core.models import HouseholdScopedModel


class Task(HouseholdScopedModel):
    """Pendiente suelto, no derivado de una regla.

    Deliberadamente separado de Obligation: una obligacion la genera el sistema
    a partir de un dato (una poliza vence, un pack lo manda) y se regenera sola;
    una tarea la escribe una persona y nadie mas la va a volver a crear.
    Mezclarlas haria que borrar una tarea la resucitara en la siguiente corrida.
    """

    class Priority(models.TextChoices):
        LOW = "low", "Baja"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"

    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        DONE = "done", "Hecha"
        DROPPED = "dropped", "Descartada"

    title = models.CharField(max_length=250)
    notes = models.TextField(blank=True)
    due_on = models.DateField(null=True, blank=True, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    assigned_to = models.ForeignKey(
        "core.Party", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due_on", "-created_at"]
        indexes = [models.Index(fields=["household", "status", "due_on"])]

    def __str__(self):
        return self.title
