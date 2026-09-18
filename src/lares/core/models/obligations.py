"""Primitiva 5 - Obligation: el motor que hace util al sistema.

Guardar datos no sirve de nada. Lo que sirve es que el sistema convierta un
dato estatico ("la poliza vence el 15/oct") en algo que te interrumpe a tiempo.

Dos niveles:
  ObligationRule  - la regla declarativa (viene de un pack de jurisdiccion o
                    de un ObligationProvider de un modulo)
  Obligation      - la instancia materializada con fecha concreta

La materializacion es idempotente por `dedupe_key`. Esto no es un detalle:
sin ello, cada reinicio del scheduler duplica los avisos y el usuario deja de
confiar en el sistema, que es la unica forma real de que un PRP muera.
"""

import datetime as dt

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .base import HouseholdScopedModel


class ObligationRule(HouseholdScopedModel):
    """Regla declarativa. Puede venir de un pack YAML o crearla el usuario."""

    key = models.CharField(max_length=80, db_index=True)
    label = models.CharField(max_length=200)
    source_pack = models.CharField(max_length=80, blank=True)

    applies_to_kind = models.CharField(max_length=40, blank=True)
    subject_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.CASCADE
    )
    subject_id = models.UUIDField(null=True, blank=True)
    subject = GenericForeignKey("subject_type", "subject_id")

    # {"yearly": {"month": 1, "day": 31}} | {"every": "3 months"} | {"rrule": "..."}
    schedule = models.JSONField(default=dict)
    remind_offsets = models.JSONField(default=list, blank=True)   # [-60, -30, -7]

    amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    counterparty = models.ForeignKey(
        "core.Party", null=True, blank=True, on_delete=models.SET_NULL, related_name="rules"
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["household", "key", "is_active"])]

    def __str__(self):
        return self.label


class Obligation(HouseholdScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        DONE = "done", "Cumplida"
        WAIVED = "waived", "No aplica"
        OVERDUE = "overdue", "Vencida"

    class Severity(models.TextChoices):
        LOW = "low", "Baja"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Critica"

    # Clave estable que hace idempotente la generacion:
    # "vehicle:<uuid>:verificacion:2026-S2"
    dedupe_key = models.CharField(max_length=200, db_index=True)

    title = models.CharField(max_length=250)
    subject_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.CASCADE
    )
    subject_id = models.UUIDField(null=True, blank=True)
    subject = GenericForeignKey("subject_type", "subject_id")

    rule = models.ForeignKey(
        ObligationRule, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="obligations",
    )
    source = models.CharField(max_length=80, blank=True)   # modulo o pack que la genero

    due_on = models.DateField(db_index=True)
    window_start = models.DateField(null=True, blank=True)

    amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    counterparty = models.ForeignKey(
        "core.Party", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="obligations",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.NORMAL)

    assigned_to = models.ForeignKey(
        "core.Party", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_obligations",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    evidence = models.ForeignKey(
        "core.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    remind_offsets = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["due_on"]
        constraints = [
            models.UniqueConstraint(fields=["household", "dedupe_key"], name="uniq_obligation"),
        ]
        indexes = [
            models.Index(fields=["household", "status", "due_on"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.due_on})"

    @property
    def days_left(self) -> int:
        return (self.due_on - dt.date.today()).days

    @property
    def urgency(self) -> str:
        """Como se pinta. El color aqui es informacion, no decoracion."""
        days = self.days_left
        if days < 0:
            return "overdue"
        if days <= 7 or self.severity in ("high", "critical"):
            return "soon"
        return "calm"


class Reminder(HouseholdScopedModel):
    """Aviso concreto derivado de una obligacion. Tambien idempotente."""

    obligation = models.ForeignKey(
        Obligation, on_delete=models.CASCADE, related_name="reminders"
    )
    fire_on = models.DateField(db_index=True)
    channel = models.CharField(max_length=20, default="email")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["obligation", "fire_on", "channel"], name="uniq_reminder"
            ),
        ]
