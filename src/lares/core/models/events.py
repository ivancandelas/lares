"""Primitiva 6 - Event: linea de tiempo append-only.

Nunca se actualiza ni se borra. Es, a la vez:
  - la bitacora de auditoria
  - el historial visible de cada entidad ("que le ha pasado a este auto")
  - el bus de eventos entre modulos
  - el corpus que consulta el copiloto

Un modulo emite `document.classified` y otro reacciona sin que ninguno de los
dos se conozca.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.dispatch import Signal

from ..ids import uuid7

# Bus de eventos. Los modulos se suscriben en LaresModule.connect_signals().
lares_event = Signal()   # kwargs: household, verb, subject, payload


class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    household = models.ForeignKey(
        "core.Household", on_delete=models.CASCADE, related_name="events"
    )
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    # "vehicle.created", "obligation.completed", "document.classified"
    verb = models.CharField(max_length=80, db_index=True)
    source = models.CharField(max_length=80, blank=True)

    actor = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="events"
    )

    subject_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    subject_id = models.UUIDField(null=True, blank=True)
    subject = GenericForeignKey("subject_type", "subject_id")

    summary = models.CharField(max_length=300, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at"]
        indexes = [
            models.Index(fields=["household", "-at"]),
            models.Index(fields=["household", "subject_type", "subject_id", "-at"]),
        ]

    def __str__(self):
        return f"{self.at:%Y-%m-%d} {self.verb}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Event es append-only: no se puede modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Event es append-only: no se puede borrar.")
