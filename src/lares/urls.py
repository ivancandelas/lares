import importlib.util

from django.apps import apps
from django.contrib import admin
from django.urls import include, path

from lares.core.registry import LaresModule

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("lares.core.urls")),
]

# Cada modulo publica sus rutas con solo tener un urls.py. El nucleo no
# mantiene una lista de modulos conocidos.
for app_config in apps.get_app_configs():
    if isinstance(app_config, LaresModule):
        if importlib.util.find_spec(f"{app_config.name}.urls"):
            urlpatterns.append(path("", include(f"{app_config.name}.urls")))
