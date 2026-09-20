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
    ContactPoint,
    Document,
    EmergencyContact,
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
            _seed_contacts(household)
            _seed_rules(household)
            _seed_succession(household)
            _seed_care(household)

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
    # Ninguna repite algo que ya lleve un modulo: el agua y la luz son
    # servicios del inmueble, no reglas escritas a mano. Duplicarlas sacaria
    # el gasto del mes al doble, que es justo lo que avisa el hueco
    # `core.duplicate_recurring`.
    reglas = [
        ("colegiatura", "Colegiatura", {"monthly": {"day": 10}}, 4500),
        ("piano", "Clases de piano de Diego",
         {"monthly": {"day": proximo.day}}, 1180),
        ("colonos", "Cuota de la asociación de colonos",
         {"every": {"months": 2}, "from": "2026-02-15"}, 640),
    ]
    for key, label, schedule, amount in reglas:
        ObligationRule.objects.get_or_create(
            household=household, key=key,
            defaults={"label": label, "schedule": schedule, "amount": amount,
                      "currency": household.currency, "remind_offsets": [-7, -3, -1]},
        )


def _seed_contacts(household):
    """Familia y amigos, con lo que hace falta para poder llamarles."""
    from lares.core.models.tagging import set_tags

    gente = [
        ("Mariana", dt.date(1988, 6, 14), "familia, casa",
         [("phone", "33 1234 5678", "móvil"), ("email", "mariana@example.mx", "")]),
        ("Diego", dt.date(2011, 3, 2), "familia, casa",
         [("phone", "33 2345 6789", "móvil")]),
        ("Luis", dt.date(1982, 11, 27), "familia",
         [("phone", "33 3456 7890", "móvil")]),
        ("Dra. Robles", None, "salud",
         [("phone", "33 4567 8901", "consultorio")]),
        ("Plomería Hernández", None, "servicios",
         [("phone", "33 5678 9012", "taller")]),
    ]
    for nombre, cumple, etiquetas, contactos in gente:
        party, _ = Party.objects.get_or_create(
            household=household, name=nombre,
            defaults={"kind": Party.Kind.PERSON},
        )
        if cumple and not party.birth_date:
            party.birth_date = cumple
            party.save(update_fields=["birth_date", "updated_at"])
        set_tags(party, etiquetas.split(","))
        for canal, valor, etiqueta in contactos:
            ContactPoint.objects.get_or_create(
                household=household, party=party, channel=canal, value=valor,
                defaults={"label": etiqueta},
            )


def _seed_succession(household):
    """Un contacto de emergencia armado, que es como se ve en reposo.

    Se siembra armado y no avisado a proposito: el demo tiene que ensenar el
    estado normal -nadie ha dejado de entrar- y no el de la emergencia, que es
    el que nadie quiere ver por sorpresa al abrir la pantalla.
    """
    mariana = Party.objects.filter(household=household, name="Mariana").first()
    EmergencyContact.objects.get_or_create(
        household=household, name="Mariana",
        defaults={
            "party": mariana,
            "relationship": "pareja",
            "email": "mariana@example.mx",
            "note": ("La caja fuerte está en el clóset de arriba. La escritura "
                     "de la casa y las pólizas están escaneadas aquí; los "
                     "originales, en la carpeta verde."),
            "quiet_days": 45,
            "grace_days": 7,
        },
    )


def _seed_care(household):
    """Un reparto a medias, que es como está en la vida real.

    Se deja algo sin nadie a cargo a proposito: el valor de esa pantalla no es
    ver quien lleva que, es ver lo que no lleva nadie.
    """
    from lares.core.models.resource import Resource
    from lares.core.services import responsibilities

    quien = {
        "property": "Mariana",
        "vehicle": None,          # los coches, sin repartir
    }
    personas = {p.name: p for p in Party.objects.filter(household=household)}
    for recurso in Resource.objects.filter(household=household,
                                           status=Resource.Status.ACTIVE):
        nombre = quien.get(recurso.kind)
        persona = personas.get(nombre) if nombre else None
        if persona and not responsibilities.responsible_of(recurso.as_concrete()):
            responsibilities.set_responsible(household, recurso.as_concrete(),
                                             persona)
