"""Datos de demostracion para ver el sistema funcionando.

El nucleo crea el hogar y las partes basicas; cada modulo siembra lo suyo a
traves de `registry.demo_seeder`. Asi este comando no importa ningun modulo.
Solo para desarrollo.
"""

import datetime as dt

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from lares.core.models import (
    Document,
    Household,
    Location,
    Membership,
    ObligationRule,
    Party,
    User,
)
from lares.core.registry import registry
from lares.core.scoping import use_household
from lares.core.services import checks, obligations


class Command(BaseCommand):
    help = "Siembra un hogar de ejemplo con datos suficientes para ver el tablero."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Casa de ejemplo")

    def handle(self, *args, **options):
        name = options["name"]
        household, _ = Household.objects.get_or_create(
            slug=slugify(name), defaults={"name": name}
        )

        with use_household(household):
            titular, _ = Party.objects.get_or_create(
                household=household, name="Titular", defaults={"is_self": True}
            )
            # Sin miembros no hay a quien avisar: los recordatorios se
            # generarian y no saldrian nunca.
            for user in User.objects.filter(is_superuser=True):
                Membership.objects.get_or_create(
                    household=household, user=user,
                    defaults={"role": Membership.Role.OWNER, "accepted_at": timezone.now()},
                )
            Party.objects.get_or_create(
                household=household, name="Aseguradora GNP",
                defaults={"kind": Party.Kind.ORGANIZATION},
            )
            Location.objects.get_or_create(household=household, name="Cochera")
            _seed_documents(household, titular)
            _seed_rules(household)

            for seeder in registry.demo_seeders:
                summary = seeder(household)
                if summary:
                    self.stdout.write(f"  {summary}")

        result = obligations.materialize(household)
        findings = checks.run_all(household)
        self.stdout.write(self.style.SUCCESS(
            f"Hogar '{household.name}' listo. "
            f"Obligaciones nuevas: {result['created']}. Huecos detectados: {len(findings)}."
        ))


def _seed_documents(household, owner):
    """Documentos con vencimiento: lo que mejor demuestra el motor.

    Un pasaporte no se renueva en una tarde -hay cita previa y semanas de
    espera-, asi que el aviso tiene que salir con muchisima antelacion. Es el
    caso que justifica que el sistema exista.
    """
    hoy = dt.date.today()
    ejemplos = [
        ("Pasaporte del titular", "passport", hoy + dt.timedelta(days=240)),
        ("Licencia de conducir", "drivers_license", hoy + dt.timedelta(days=52)),
        ("Credencial de elector (INE)", "id_card", hoy + dt.timedelta(days=430)),
    ]
    for title, doc_type, expires in ejemplos:
        Document.objects.get_or_create(
            household=household, title=title,
            defaults={"doc_type": doc_type, "expires_on": expires, "issuer": None},
        )


def _seed_rules(household):
    """Reglas que escribiria el propio usuario, no un modulo ni un pack.

    El recibo de la luz se coloca unos dias por delante de hoy a proposito: sin
    algo inminente, el demo no ensena como se ve lo que de verdad importa.
    """
    proximo = dt.date.today() + dt.timedelta(days=4)
    reglas = [
        ("colegiatura", "Colegiatura", {"monthly": {"day": 10}}, 4500),
        ("recibo_luz", "Recibo de luz", {"monthly": {"day": proximo.day}}, 1180),
        ("agua", "Recibo de agua", {"every": {"months": 2}, "from": "2026-02-15"}, 640),
    ]
    for key, label, schedule, amount in reglas:
        ObligationRule.objects.get_or_create(
            household=household, key=key,
            defaults={"label": label, "schedule": schedule, "amount": amount,
                      "currency": household.currency, "remind_offsets": [-7, -3, -1]},
        )
