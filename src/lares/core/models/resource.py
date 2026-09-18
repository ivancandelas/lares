"""Primitiva 2 - Resource: todo lo que se posee.

Casa, auto, laptop, poliza, suscripcion, cuenta bancaria: todos heredan de
Resource mediante herencia multi-tabla. Eso da una tabla real con los campos
comunes, lo que permite:

  - "muestrame todo lo que tengo" en una consulta
  - que Link, Document y Obligation apunten a una FK real y no solo generica
  - busqueda global y calculo de patrimonio sin recorrer cada modulo

El costo es un JOIN por consulta a una hija. Vale la pena. Ver ADR-0008.
"""

import decimal

from django.db import models

from .base import HouseholdScopedModel


class Location(HouseholdScopedModel):
    """Ubicacion fisica jerarquica: Casa > Oficina > Cajon."""

    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    # Etiqueta QR/NFC pegada al lugar o al objeto.
    code = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Resource(HouseholdScopedModel):
    """Base concreta de todo recurso. Los modulos heredan de aqui."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planeado"
        ACTIVE = "active", "Activo"
        SUSPENDED = "suspended", "Suspendido"
        DISPOSED = "disposed", "Dado de baja"

    # Clave del tipo registrado por el modulo: "vehicle", "property", "policy".
    kind = models.CharField("tipo", max_length=40, db_index=True)

    name = models.CharField("nombre", max_length=200)
    description = models.TextField("descripción", blank=True)
    status = models.CharField("estado", max_length=20, choices=Status.choices,
                              default=Status.ACTIVE)

    owner = models.ForeignKey(
        "core.Party", verbose_name="propietario", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_resources",
    )
    # Quien lo usa o lo custodia, que no siempre es el propietario.
    custodian = models.ForeignKey(
        "core.Party", verbose_name="a cargo de", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="custody_of",
    )
    location = models.ForeignKey(
        Location, verbose_name="ubicación", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="resources",
    )

    acquired_on = models.DateField("adquirido el", null=True, blank=True)
    disposed_on = models.DateField("dado de baja el", null=True, blank=True)

    purchase_amount = models.DecimalField("lo que costó", max_digits=16,
                                          decimal_places=2, null=True, blank=True)
    current_value = models.DecimalField("valor actual", max_digits=16,
                                        decimal_places=2, null=True, blank=True)
    valuation_date = models.DateField("valorado el", null=True, blank=True)
    currency = models.CharField("moneda", max_length=3, blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["household", "kind", "status"]),
            models.Index(fields=["household", "status", "name"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.kind:
            self.kind = getattr(self, "resource_kind", "") or ""
        super().save(*args, **kwargs)

    def context_line(self) -> str:
        """Los datos secundarios de la ficha, en una linea.

        Se arma aqui y no en la plantilla porque encadenar `{% if %}` para
        decidir si toca una coma deja espacios sueltos antes del signo, y el
        resultado se lee mal.
        """
        partes = [
            str(self.owner) if self.owner else "",
            f"en {self.location}" if self.location else "",
            f"desde {self.acquired_on:%Y}" if self.acquired_on else "",
        ]
        return ", ".join(p for p in partes if p)

    OCULTOS = {"id", "household", "created_at", "updated_at", "archived_at",
               "extra", "kind", "resource_ptr", "description", "name"}

    def facts(self) -> list:
        """Los datos de la ficha, como pares etiqueta/valor.

        Se derivan del modelo para que un modulo nuevo tenga ficha sin escribir
        ninguna plantilla.
        """
        propios, heredados = [], []
        for field in self._meta.fields:
            if field.name in self.OCULTOS:
                continue
            valor = getattr(self, field.name, None)
            if valor in (None, ""):
                continue
            if field.choices:
                valor = getattr(self, f"get_{field.name}_display")()
            elif isinstance(valor, decimal.Decimal):
                valor = f"{valor:,.2f}".rstrip("0").rstrip(".")
            par = (str(field.verbose_name).capitalize(), valor)
            # Lo que define a un coche es la placa, no el estado del registro.
            (propios if field.model is not Resource else heredados).append(par)
        return propios + heredados

    def as_concrete(self):
        """Devuelve la instancia de la subclase real (Vehicle, Property...).

        Necesario porque una consulta sobre Resource devuelve Resource. Usarlo
        de a uno; para recorrer muchos, consultar el modelo concreto.
        """
        from ..registry import registry

        model = registry.resource_kinds.get(self.kind)
        if model is None or isinstance(self, model):
            return self
        return model.objects.filter(pk=self.pk).first() or self
