"""Enlaces compartidos.

Compartir sin enviar una copia: un enlace con token, de solo lectura, que se
puede revocar. La copia no se puede retirar; el enlace si.

Tres reglas que hacen que esto sea compartir y no filtrar:

  1. Alcance explicito. Se comparte una etiqueta concreta, no "los contactos".
  2. Caducidad. Un enlace sin fecha de fin acaba siendo permanente por olvido.
  3. Cuenta de accesos. Saber si alguien entro -y cuando- es la diferencia
     entre compartir y perder de vista.
"""

import datetime as dt
import secrets

from django.db import models

from .base import HouseholdScopedModel


class Share(HouseholdScopedModel):
    class Kind(models.TextChoices):
        CONTACTS = "contacts", "Contactos de una etiqueta"

    kind = models.CharField("qué se comparte", max_length=20, choices=Kind.choices,
                            default=Kind.CONTACTS)
    label = models.CharField("cómo lo llamas", max_length=160)
    # A qué se refiere: el slug de la etiqueta, por ahora.
    target = models.CharField("alcance", max_length=120, blank=True)

    token = models.CharField(max_length=43, unique=True, db_index=True)
    note = models.CharField("para quién es", max_length=200, blank=True)

    expires_on = models.DateField("caduca el", null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    last_seen_at = models.DateTimeField(null=True, blank=True)
    hits = models.PositiveIntegerField("veces abierto", default=0)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "enlace compartido"
        verbose_name_plural = "enlaces compartidos"

    def __str__(self):
        return self.label

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    @property
    def is_live(self) -> bool:
        if self.revoked_at:
            return False
        return not (self.expires_on and self.expires_on < dt.date.today())

    @property
    def state(self) -> str:
        if self.revoked_at:
            return "revocado"
        if self.expires_on and self.expires_on < dt.date.today():
            return "caducado"
        if self.expires_on:
            return f"hasta el {self.expires_on:%d/%m/%Y}"
        return "sin caducidad"

    def touch(self):
        from django.utils import timezone

        type(self).all_objects.filter(pk=self.pk).update(
            hits=models.F("hits") + 1, last_seen_at=timezone.now()
        )
