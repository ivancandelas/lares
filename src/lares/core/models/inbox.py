"""Bandeja de entrada: la unica puerta por la que entra informacion.

Es el cuello de botella real del producto. Si meter informacion cuesta trabajo,
el sistema se queda al 30%, y un PRP al 30% es peor que no tenerlo porque da
falsa tranquilidad.

Dos reglas que no se negocian:

  1. El item crudo es inmutable y se conserva siempre. Cuando el clasificador
     mejore -y va a mejorar- hay que poder reprocesar lo que entro mal.
  2. Nada se crea sin confirmacion humana. El clasificador propone; la persona
     dispone. Un sistema con datos que nadie verifico es peor que uno vacio,
     porque deja de poder distinguirse lo cierto de lo inventado.
"""

from django.db import models

from .base import HouseholdScopedModel


class InboxItem(HouseholdScopedModel):
    class Source(models.TextChoices):
        UPLOAD = "upload", "Subido"
        SHARE = "share", "Compartido desde el móvil"
        EMAIL = "email", "Correo"
        PAPERLESS = "paperless", "Paperless"
        WATCH = "watch", "Carpeta vigilada"

    class Status(models.TextChoices):
        NEW = "new", "Sin revisar"
        APPLIED = "applied", "Registrado"
        DISCARDED = "discarded", "Descartado"

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.UPLOAD)
    original_name = models.CharField(max_length=300, blank=True)
    file = models.FileField(upload_to="inbox/%Y/%m/", null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)

    # Reenviar dos veces el mismo correo no debe crear nada dos veces.
    checksum = models.CharField(max_length=64, db_index=True)

    # De donde viene, cuando el binario vive fuera: "paperless:1827".
    # Lares no quiere ser un gestor documental -Paperless ya lo es- asi que lo
    # que entra por ahi se referencia en vez de copiarse. Ver docs/07-ingestion.md
    external_ref = models.CharField(max_length=200, blank=True, db_index=True)

    # Texto extraido, para poder reclasificar sin volver a abrir el archivo.
    text = models.TextField(blank=True)
    note = models.CharField(max_length=300, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    applied_document = models.ForeignKey(
        "core.Document", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="from_inbox",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["household", "checksum"], name="uniq_inbox_item"),
            # Lo de fuera se identifica por su referencia y no por sus bytes,
            # que a proposito no tenemos. Sin esto, un webhook que se repite
            # -y se repite- crearia dos entradas del mismo documento.
            models.UniqueConstraint(
                fields=["household", "external_ref"],
                condition=models.Q(external_ref__gt=""),
                name="uniq_inbox_external_ref",
            ),
        ]

    def __str__(self):
        return self.original_name or f"Entrada {self.pk}"

    @property
    def suggestion(self):
        return self.suggestions.order_by("-confidence").first()

    @property
    def is_reference(self) -> bool:
        """El archivo vive fuera: aquí solo está lo que significa."""
        return bool(self.external_ref) and not self.file


class Suggestion(HouseholdScopedModel):
    """Lo que el clasificador cree que es. Nunca se aplica solo."""

    item = models.ForeignKey(InboxItem, on_delete=models.CASCADE, related_name="suggestions")
    classifier = models.CharField(max_length=80)
    label = models.CharField(max_length=200)
    confidence = models.FloatField(default=0.5)

    # Lo que se crearia al confirmar: {"document": {...}, "party": {...}, ...}
    plan = models.JSONField(default=dict)

    class Meta:
        ordering = ["-confidence"]

    def __str__(self):
        return self.label

    @property
    def confidence_pct(self) -> int:
        return round(self.confidence * 100)
