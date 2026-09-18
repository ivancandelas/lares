from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "lares.core"
    label = "core"
    verbose_name = "Nucleo"

    def ready(self):
        from . import receivers  # noqa: F401
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
            NavItem(label="Patrimonio", url_name="core:holdings", icon="box", order=10),
            NavItem(label="Documentos", url_name="core:documents", icon="file", order=50),
            NavItem(label="Personas", url_name="core:parties", icon="users", order=60),
            NavItem(label="Recurrentes", url_name="core:rules", icon="repeat", order=70),
            NavItem(label="Bandeja", url_name="core:inbox", icon="inbox", order=5),
            NavItem(label="Conectores", url_name="core:connectors", icon="plug", order=80),
        )
        registry.subject_source("document", _expiring_documents)
        registry.subject_source("household", lambda household: [household])
        registry.obligations(DocumentExpiryProvider, UserRuleProvider)
        # El CFDI va primero: está firmado, no se adivina.
        registry.classifier(CfdiClassifier, KeywordClassifier)

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
