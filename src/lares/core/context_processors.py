from django.conf import settings

from .models import InboxItem
from .registry import registry


def product(request):
    household = getattr(request, "household", None)
    return {
        "product_name": settings.PRODUCT_NAME,
        "product_tagline": settings.PRODUCT_TAGLINE,
        "tenancy_mode": settings.TENANCY_MODE,
        "nav_groups": registry.nav_grouped(),
        "current_household": household,
        "inbox_pending": _pendientes(household),
        "current_url_name": _actual(request),
    }


def _pendientes(household) -> int:
    """Lo que espera en la bandeja, para el contador del menú.

    Es la única consulta que se hace en cada página: vale la pena porque es lo
    que trae de vuelta al usuario.
    """
    if household is None:
        return 0
    return InboxItem.all_objects.filter(
        household=household, status=InboxItem.Status.NEW
    ).count()


def _actual(request) -> str:
    """Ruta activa, para marcar dónde está el usuario."""
    match = getattr(request, "resolver_match", None)
    return match.view_name if match else ""
