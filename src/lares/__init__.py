"""Lares - Personal Resource Planning, self-hosted."""

# Importar aqui la app de Celery no es decorativo: sin esto, @shared_task se
# engancha a la app por defecto, ignora la configuracion de Django e intenta
# hablar con un broker que no existe.
from .celery import app as celery_app

__version__ = "0.0.1"

__all__ = ["celery_app"]
