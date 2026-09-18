"""Conectores: de donde llega informacion sin que nadie la suba a mano.

El nucleo no sabe hablar con Paperless ni con un buzon IMAP. Solo sabe que hay
conectores, que se ejecutan cada cierto tiempo y que todo lo que traigan entra
por la bandeja, igual que si lo hubieras arrastrado tu.
"""

from django.db import models

from ..services.secrets_store import decrypt, encrypt
from .base import HouseholdScopedModel


class Connector(HouseholdScopedModel):
    key = models.CharField(max_length=40, db_index=True)
    label = models.CharField(max_length=120, blank=True)

    # Lo que no es secreto: url, carpeta, remitentes permitidos.
    config = models.JSONField(default=dict, blank=True)
    # Lo que sí lo es, cifrado en reposo.
    secret_encrypted = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_count = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=400, blank=True)

    class Meta:
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(fields=["household", "key", "label"],
                                    name="uniq_connector"),
        ]

    def __str__(self):
        return self.label or self.key

    @property
    def secret(self) -> str:
        return decrypt(self.secret_encrypted)

    @secret.setter
    def secret(self, value: str):
        self.secret_encrypted = encrypt(value or "")

    @property
    def has_secret(self) -> bool:
        return bool(self.secret_encrypted)
