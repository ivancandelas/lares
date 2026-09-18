from django.conf import settings

from .registry import registry


def product(request):
    return {
        "product_name": settings.PRODUCT_NAME,
        "product_tagline": settings.PRODUCT_TAGLINE,
        "tenancy_mode": settings.TENANCY_MODE,
        "nav_items": registry.nav_sorted(),
        "current_household": getattr(request, "household", None),
    }
