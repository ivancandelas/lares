from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "lares.core"
    label = "core"
    verbose_name = "Nucleo"

    def ready(self):
        from . import (
            packs,
            receivers,  # noqa: F401
        )
        from .classifiers import CfdiClassifier, KeywordClassifier
        from .connectors import ImapRunner, PaperlessRunner, WatchFolderRunner
        from .forms import (
            ImapConnectorForm,
            PaperlessConnectorForm,
            WatchFolderConnectorForm,
        )
        from .providers import (
            BirthdayProvider,
            DocumentExpiryProvider,
            UserRuleProvider,
        )
        from .registry import LinkRole, NavItem, registry

        registry.nav(
            NavItem("Bandeja", "core:inbox", icon="inbox", order=10, section="main"),
            NavItem("Todo lo que tienes", "core:holdings", icon="box", order=5,
                    section="holdings"),
            NavItem("Quién debe a quién", "core:owed", icon="scale",
                    order=19, section="money"),
            NavItem("Documentos", "core:documents", icon="file", order=90,
                    section="holdings"),
            NavItem("Pagos recurrentes", "core:rules", icon="repeat", order=20,
                    section="money"),
            NavItem("Personas", "core:parties", icon="users", order=10,
                    section="more"),
            NavItem("Quién se encarga de qué", "core:responsibilities",
                    icon="users", order=12, section="more"),
            NavItem("Qué tengo compartido", "core:shares", icon="link",
                    order=28, section="more"),
            NavItem("Si me pasa algo", "core:succession", icon="shield",
                    order=29, section="more"),
            NavItem("El hogar", "core:household", icon="home", order=15,
                    section="more"),
            NavItem("Qué ha pasado", "core:audit", icon="history", order=18,
                    section="more"),
            NavItem("Conectores", "core:connectors", icon="plug", order=20,
                    section="more"),
            NavItem("Calendario", "core:calendar-settings", icon="calendar",
                    order=25, section="more"),
            NavItem("Por dónde seguir", "core:onboarding", icon="compass", order=30,
                    section="more"),
        )
        # Quién se encarga de qué. Es una arista y no una columna porque es un
        # papel que alguien juega frente a una cosa -como "propietario" o
        # "asegurado por"- y porque tiene historia: quién se encargaba de la
        # casa en 2025 se sigue pudiendo leer.
        registry.link_role(LinkRole(
            key="cared_by", label="A cargo de",
            inverse_key="cares_for", inverse_label="Se encarga de",
        ))

        from .checks import DuplicateRecurring
        registry.check(DuplicateRecurring)

        registry.subject_source("document", _expiring_documents)
        registry.subject_source("household", lambda household: [household])
        registry.subject_source("party", _people)
        registry.obligations(DocumentExpiryProvider, UserRuleProvider,
                             BirthdayProvider)
        # El CFDI va primero: está firmado, no se adivina.
        registry.classifier(CfdiClassifier, KeywordClassifier)

        from .related import for_party
        registry.related(for_party)

        # Lo que se puede crear al vuelo desde un desplegable, sin perder el
        # formulario que se estaba llenando. Ver `quickadd.py`.
        from . import quickadd
        quickadd.poblar()

        # Las reglas que cambian por estado y por año viven en packs/*.yaml.
        # Cambiar una fecha no debería exigir un despliegue.
        packs.register(registry)

        for runner, form in (
            (PaperlessRunner, PaperlessConnectorForm),
            (ImapRunner, ImapConnectorForm),
            (WatchFolderRunner, WatchFolderConnectorForm),
        ):
            instancia = runner()
            instancia.form_class = form
            registry.connector(instancia.key, instancia)


def _expiring_documents(household):
    from .models import Document

    return Document.objects.filter(expires_on__isnull=False, archived_at__isnull=True)


def _people(household):
    from .models import Party

    return Party.objects.filter(kind=Party.Kind.PERSON, archived_at__isnull=True)
