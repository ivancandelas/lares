"""Primitiva 4 - Document.

Lares no quiere ser un gestor documental: Paperless-ngx ya lo es y lo hace
bien. Lares es dueno del SIGNIFICADO del documento (que es, a que entidad
pertenece, cuando vence, cuanto cuesta) y referencia el binario, este donde
este. Ver docs/07-ingestion.md
"""

from django.db import models

from .base import HouseholdScopedModel


class Document(HouseholdScopedModel):
    class Confidentiality(models.TextChoices):
        NORMAL = "normal", "Normal"
        PRIVATE = "private", "Privado"          # cifrado extremo a extremo
        SECRET = "secret", "Secreto"            # zero-knowledge, servidor ciego

    title = models.CharField(max_length=250)
    # Clave registrada por un modulo: "policy", "invoice", "statement", "deed".
    doc_type = models.CharField(max_length=40, db_index=True, blank=True)

    file = models.FileField(upload_to="documents/%Y/%m/", null=True, blank=True)
    # Cuando el binario vive fuera: "paperless:1234", "nextcloud:/ruta".
    external_ref = models.CharField(max_length=200, blank=True, db_index=True)
    checksum = models.CharField(max_length=64, blank=True, db_index=True)
    mime_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)

    issuer = models.ForeignKey(
        "core.Party", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="issued_documents",
    )
    issued_on = models.DateField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    # Si tiene fecha de vencimiento, el nucleo genera la obligacion sola.
    expires_on = models.DateField(null=True, blank=True, db_index=True)

    amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)

    confidentiality = models.CharField(
        max_length=20, choices=Confidentiality.choices, default=Confidentiality.NORMAL
    )
    ocr_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-issued_on", "-created_at"]
        indexes = [
            models.Index(fields=["household", "doc_type", "expires_on"]),
        ]

    def __str__(self):
        return self.title
