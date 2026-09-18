"""Crea el hogar inicial de una instalacion self-hosted."""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from lares.core.models import Household


class Command(BaseCommand):
    help = "Crea el hogar inicial (modo self-hosted)."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Mi hogar")

    def handle(self, *args, **options):
        name = options["name"]
        household, created = Household.objects.get_or_create(
            slug=slugify(name),
            defaults={
                "name": name,
                "country": settings.DEFAULT_COUNTRY,
                "subdivision": settings.DEFAULT_SUBDIVISION,
                "timezone": settings.TIME_ZONE,
                "currency": settings.DEFAULT_CURRENCY,
            },
        )
        verb = "Creado" if created else "Ya existia"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {household.name} ({household.pk})"))
