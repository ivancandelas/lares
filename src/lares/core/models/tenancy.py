"""Hogares, usuarios y membresias.

El hogar (Household) es la frontera de aislamiento: en self-hosted hay uno,
en SaaS hay miles y el codigo es el mismo. Un usuario puede pertenecer a
varios hogares, lo que resuelve de forma natural "administro tambien la casa
de mis padres" y, de paso, es exactamente el modelo que necesita el SaaS.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models

from ..ids import uuid7
from .base import TimestampedModel


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=120, blank=True)
    locale = models.CharField(max_length=10, default="es-mx")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.display_name or self.email


class Household(TimestampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)

    # Determina que packs de obligaciones aplican (predial, refrendo,
    # verificacion...). Es un dato, no codigo. Ver docs/03-module-system.md
    country = models.CharField(max_length=2, default="MX")
    subdivision = models.CharField(max_length=10, blank=True, default="MX-JAL")
    timezone = models.CharField(max_length=64, default="America/Mexico_City")
    currency = models.CharField(max_length=3, default="MXN")

    members = models.ManyToManyField(
        User,
        through="Membership",
        through_fields=("household", "user"),
        related_name="households",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(TimestampedModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Titular"
        ADMIN = "admin", "Administrador"
        ADULT = "adult", "Adulto"
        MEMBER = "member", "Miembro"
        VIEWER = "viewer", "Solo lectura"
        # Acceso acotado para un tercero: contador, abogado, albacea.
        PROFESSIONAL = "professional", "Profesional externo"

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)

    # Visibilidad granular: que dominios puede ver este miembro.
    # Vacio = todo lo que permita su rol. Ver docs/06-privacy-and-security.md
    scopes = models.JSONField(default=list, blank=True)

    invited_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="invitations_sent"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["household", "user"], name="uniq_membership"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.household} ({self.role})"
