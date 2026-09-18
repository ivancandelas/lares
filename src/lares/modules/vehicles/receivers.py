"""Ejemplo de acoplamiento por eventos, no por importaciones.

El modulo de vehiculos escucha `document.classified` del pipeline de ingesta
sin conocerlo, y el pipeline no sabe que existen los vehiculos.
"""

from django.dispatch import receiver

from lares.core.models import lares_event


@receiver(lares_event)
def on_document_classified(sender, verb=None, payload=None, **kwargs):
    if verb != "document.classified":
        return
    # F2: si el documento es una factura de taller o una poliza de auto,
    # proponer la arista contra el vehiculo correspondiente.
    return
