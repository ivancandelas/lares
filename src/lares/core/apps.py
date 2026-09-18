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
        from .providers import DocumentExpiryProvider, UserRuleProvider
        from .registry import NavItem, registry

        registry.nav(
            NavItem("Bandeja", "core:inbox", icon="inbox", order=10, section="main"),
            NavItem("Todo lo que tienes", "core:holdings", icon="box", order=5,
                    section="holdings"),
            NavItem("Documentos", "core:documents", icon="file", order=90,
                    section="holdings"),
            NavItem("Pagos recurrentes", "core:rules", icon="repeat", order=20,
                    section="money"),
            NavItem("Personas", "core:parties", icon="users", order=10, section="more"),
            NavItem("Conectores", "core:connectors", icon="plug", order=20,
                    section="more"),
            NavItem("Por dónde seguir", "core:onboarding", icon="compass", order=30,
                    section="more"),
        )
        registry.subject_source("document", _expiring_documents)
        registry.subject_source("household", lambda household: [household])
        registry.obligations(DocumentExpiryProvider, UserRuleProvider)
        # El CFDI va primero: está firmado, no se adivina.
        registry.classifier(CfdiClassifier, KeywordClassifier)

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
