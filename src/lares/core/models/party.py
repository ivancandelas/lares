"""Primitiva 1 - Party: cualquier actor.

Personas, familia, contactos, proveedores, aseguradoras, escuelas, bancos y
dependencias de gobierno son todos Party. No hay modelos separados para
"proveedor" o "aseguradora": el papel que juega una parte se expresa como
arista del grafo (Link), no como tabla.

Esto evita el error clasico de tener a GNP tres veces: como aseguradora del
auto, como aseguradora de la casa y como contacto.
"""

from django.db import models

from .base import HouseholdScopedModel


class Party(HouseholdScopedModel):
    class Kind(models.TextChoices):
        PERSON = "person", "Persona"
        ORGANIZATION = "organization", "Organización"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PERSON)
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)

    # Identificador fiscal. En Mexico el RFC es la clave canonica de un
    # proveedor y es lo que permite conciliar CFDIs contra partes.
    tax_id = models.CharField(max_length=20, blank=True, db_index=True)

    # La persona del titular de la instalacion.
    is_self = models.BooleanField(default=False)
    user = models.OneToOneField(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="party"
    )

    birth_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["household", "kind", "name"])]

    def __str__(self):
        return self.name


class ContactPoint(HouseholdScopedModel):
    class Channel(models.TextChoices):
        EMAIL = "email", "Correo"
        PHONE = "phone", "Telefono"
        ADDRESS = "address", "Direccion"
        WEB = "web", "Sitio web"
        OTHER = "other", "Otro"

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="contact_points")
    channel = models.CharField(max_length=20, choices=Channel.choices)
    label = models.CharField(max_length=60, blank=True)
    value = models.CharField(max_length=400)
    is_primary = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.party}: {self.value}"
