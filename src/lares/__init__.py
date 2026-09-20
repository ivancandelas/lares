"""Lares - Personal Resource Planning, self-hosted."""

# Importar aqui la app de Celery no es decorativo: sin esto, @shared_task se
# engancha a la app por defecto, ignora la configuracion de Django e intenta
# hablar con un broker que no existe.
from .celery import app as celery_app


def _version() -> str:
    """La version que corre, leida del archivo VERSION de la raiz.

    Un solo sitio donde tocarla. En la imagen de Docker el archivo se copia, y
    si no estuviera -alguien ejecutando desde un zip- se dice "desconocida" en
    vez de mentir con un numero viejo.
    """
    from pathlib import Path

    archivo = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return archivo.read_text().strip() or "desconocida"
    except OSError:
        return "desconocida"


__version__ = _version()

__all__ = ["celery_app"]
