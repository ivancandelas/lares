"""Llaves de API y webhooks: como entra y sale informacion sin pasar por la web.

Existen desde F1 a proposito. Una API que se anade tarde obliga a rehacer las
vistas, y sin ella no hay ecosistema de conectores ni forma de que el copiloto
consulte el grafo.
"""

from __future__ import annotations

import hashlib
import secrets

from django.db import models

from .base import HouseholdScopedModel

PREFIX_LEN = 8


class ApiKey(HouseholdScopedModel):
    """Se guarda el hash, nunca la llave.

    Si la base se filtra, las llaves siguen sin servir. El prefijo se guarda en
    claro solo para poder localizar la fila y para que el usuario reconozca cual
    revocar.
    """

    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=PREFIX_LEN, db_index=True)
    key_hash = models.CharField(max_length=64)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    @classmethod
    def issue(cls, household, name: str) -> tuple[ApiKey, str]:
        """Crea una llave y devuelve el texto completo, que solo se ve una vez."""
        prefix = secrets.token_hex(PREFIX_LEN // 2)
        secret = secrets.token_urlsafe(32)
        token = f"{prefix}.{secret}"
        key = cls.objects.create(
            household=household, name=name, prefix=prefix, key_hash=_hash(token)
        )
        return key, token


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Webhook(HouseholdScopedModel):
    """Aviso saliente cuando pasa algo en el hogar."""

    url = models.URLField(max_length=500)
    # Verbos concretos ("obligation.completed") o "*" para todos.
    events = models.JSONField(default=list, blank=True)
    secret = models.CharField(max_length=64, default=secrets.token_hex)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.url

    def wants(self, verb: str) -> bool:
        return self.is_active and ("*" in self.events or verb in self.events)


class WebhookDelivery(HouseholdScopedModel):
    """Bitacora de envios. Sin ella, depurar una integracion es adivinar."""

    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name="deliveries")
    verb = models.CharField(max_length=80)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "webhook deliveries"

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300
