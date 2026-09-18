"""Etiquetas.

Sirven para lo que las categorias rigidas no: decir "familia", "trabajo",
"amigos del futbol" sin que nadie haya previsto esa lista, y luego operar sobre
el grupo entero -compartirlo, exportarlo, filtrarlo-.

Son genericas a proposito. Hoy se usan en contactos; manana en documentos o en
objetos, sin tocar este archivo.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.text import slugify

from .base import HouseholdScopedModel


class Tag(HouseholdScopedModel):
    name = models.CharField("etiqueta", max_length=60)
    slug = models.SlugField(max_length=70)

    class Meta:
        ordering = ["name"]
        verbose_name = "etiqueta"
        verbose_name_plural = "etiquetas"
        constraints = [
            models.UniqueConstraint(fields=["household", "slug"], name="uniq_tag"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:70]
        super().save(*args, **kwargs)


class TaggedItem(HouseholdScopedModel):
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="items")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    target = GenericForeignKey("content_type", "object_id")

    class Meta:
        verbose_name = "elemento etiquetado"
        verbose_name_plural = "elementos etiquetados"
        constraints = [
            models.UniqueConstraint(
                fields=["tag", "content_type", "object_id"], name="uniq_tagged"
            ),
        ]
        indexes = [models.Index(fields=["household", "content_type", "object_id"])]

    def __str__(self):
        return f"{self.target} · {self.tag}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tags_of(obj) -> list:
    return list(
        Tag.objects.filter(
            items__content_type=ContentType.objects.get_for_model(obj.__class__),
            items__object_id=obj.pk,
        ).distinct()
    )


def set_tags(obj, nombres) -> list:
    """Deja el objeto exactamente con estas etiquetas. Crea las que falten."""
    ctype = ContentType.objects.get_for_model(obj.__class__)
    limpios = [n.strip() for n in nombres if n and n.strip()]
    etiquetas = []
    for nombre in limpios:
        tag, _ = Tag.objects.get_or_create(
            household=obj.household, slug=slugify(nombre)[:70],
            defaults={"name": nombre},
        )
        etiquetas.append(tag)

    TaggedItem.objects.filter(content_type=ctype, object_id=obj.pk).exclude(
        tag__in=etiquetas
    ).delete()
    for tag in etiquetas:
        TaggedItem.objects.get_or_create(
            household=obj.household, tag=tag, content_type=ctype, object_id=obj.pk
        )
    return etiquetas


def tagged(tag, model) -> list:
    """Los objetos de un modelo que llevan una etiqueta."""
    ids = TaggedItem.objects.filter(
        tag=tag, content_type=ContentType.objects.get_for_model(model)
    ).values_list("object_id", flat=True)
    return list(model.objects.filter(pk__in=ids))
