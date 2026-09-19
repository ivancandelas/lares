from django.conf import settings

from .models import InboxItem
from .registry import registry


def product(request):
    household = getattr(request, "household", None)
    membership = getattr(request, "membership", None)
    return {
        "product_name": settings.PRODUCT_NAME,
        "product_tagline": settings.PRODUCT_TAGLINE,
        "tenancy_mode": settings.TENANCY_MODE,
        "nav_groups": registry.nav_grouped(membership),
        "membership": membership,
        "households": _otros_hogares(request),
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


def _otros_hogares(request) -> list:
    """Los hogares a los que esta persona puede entrar, si hay más de uno.

    Con uno solo no se enseña el selector: un desplegable de un elemento es
    ruido en todas las páginas.
    """
    from django.conf import settings

    if settings.TENANCY_MODE == "single":
        return []
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return []
    from .models import Membership

    vivas = [
        m for m in Membership.objects.filter(user=user,
                                             accepted_at__isnull=False)
        .select_related("household")
        if m.is_live
    ]
    return [m.household for m in vivas] if len(vivas) > 1 else []
