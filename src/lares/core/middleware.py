"""Fija el hogar activo de la peticion.

En modo `single` hay un unico hogar y se resuelve solo. En modo `multi` se
toma de la sesion, validando siempre contra las membresias del usuario: el
hogar activo nunca se acepta de un parametro sin comprobar.
"""

from django.conf import settings

from .models import Household, Membership
from .scoping import set_current_household


class HouseholdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        household = self._resolve(request)
        request.household = household
        token = set_current_household(household)
        try:
            return self.get_response(request)
        finally:
            from .scoping import _current_household

            _current_household.reset(token)

    def _resolve(self, request):
        if settings.TENANCY_MODE == "single":
            return Household.objects.first()

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        wanted = request.session.get("household_id")
        memberships = Membership.objects.filter(user=user, accepted_at__isnull=False)
        if wanted:
            membership = memberships.filter(household_id=wanted).first()
            if membership:
                return membership.household
        membership = memberships.select_related("household").first()
        return membership.household if membership else None
