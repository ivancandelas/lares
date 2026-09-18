from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "lares.core"
    label = "core"
    verbose_name = "Nucleo"

    def ready(self):
        from . import receivers  # noqa: F401
