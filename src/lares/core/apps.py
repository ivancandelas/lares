from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "lares.core"
    label = "core"
    verbose_name = "Nucleo"

    def ready(self):
        from . import receivers  # noqa: F401
        from .providers import DocumentExpiryProvider, UserRuleProvider
        from .registry import registry

        registry.subject_source("document", _expiring_documents)
        registry.subject_source("household", lambda household: [household])
        registry.obligations(DocumentExpiryProvider, UserRuleProvider)


def _expiring_documents(household):
    from .models import Document

    return Document.objects.filter(expires_on__isnull=False, archived_at__isnull=True)
