"""Fija el hogar activo de la petición y comprueba que se pueda abrir.

En modo `single` hay un unico hogar y se resuelve solo. En modo `multi` se toma
de la sesion, validando siempre contra las membresias del usuario: el hogar
activo nunca se acepta de un parametro sin comprobar.

La comprobacion de permisos va aqui y no en cada vista a proposito. Un permiso
que hay que acordarse de poner en cada pantalla nueva es un permiso que tarde o
temprano falta en una, y justo en esa esta el saldo del banco.
"""

from django.conf import settings
from django.core.exceptions import PermissionDenied

from .models import Household, Membership
from .permissions import can_open
from .scoping import set_current_household


class HouseholdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        household, membership = self._resolve(request)
        request.household = household
        request.membership = membership
        self._touch(request, household)
        token = set_current_household(household)
        try:
            return self.get_response(request)
        finally:
            from .scoping import _current_household

            _current_household.reset(token)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Cierra la puerta antes de que la vista toque nada.

        Esconder una entrada del menu no es un permiso: la direccion se puede
        teclear. Aqui se responde 403 y la vista ni se ejecuta.
        """
        if settings.TENANCY_MODE == "single":
            return None
        match = request.resolver_match
        if match is None:
            return None
        # Sin sesión no hay a quién medir: son las rutas que se abren con un
        # token -el feed del calendario, un enlace compartido, la API con
        # llave- y cada una valida el suyo.
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        # OJO: aquí NO se salta por `login_not_required`. La API acepta la
        # sesión del navegador como respaldo para leer, así que saltársela
        # dejaba a un miembro con ámbitos limitados sacar por /api/v1/ justo
        # lo que la pantalla le negaba.
        nombre = match.view_name
        if not can_open(request.membership, nombre, match.app_name,
                        request.method):
            raise PermissionDenied(
                "Tu acceso a este hogar no llega hasta aquí."
            )
        return None

    def _touch(self, request, household):
        """Deja constancia de que hoy entraste.

        Lo usa el interruptor de sucesion para medir el silencio del titular.
        `last_login` no vale: solo cambia al iniciar sesion, y quien no cierra
        nunca puede llevar meses usando el sistema con un `last_login` viejo, lo
        que liberaria un paquete de sucesion estando perfectamente vivo.

        Una escritura por persona y dia: la fecha se recuerda en la sesion.
        """
        import datetime as dt

        if household is None:
            return
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return

        hoy = dt.date.today()
        if request.session.get("seen_on") == hoy.isoformat():
            return
        Membership.objects.filter(household=household, user=user).update(
            last_seen_on=hoy
        )
        request.session["seen_on"] = hoy.isoformat()

    def _resolve(self, request):
        if settings.TENANCY_MODE == "single":
            # El mas antiguo, no el primero por nombre: `Household` ordena por
            # nombre, asi que crear un segundo hogar llamado "Casa ajena" movia
            # la instalacion entera a otro sitio sin que nada avisara.
            return Household.objects.order_by("created_at").first(), None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None, None

        vivas = [
            m for m in Membership.objects
            .filter(user=user, accepted_at__isnull=False)
            .select_related("household")
            if m.is_live
        ]
        if not vivas:
            return None, None

        querido = request.session.get("household_id")
        elegida = next((m for m in vivas if str(m.household_id) == str(querido)),
                       vivas[0])
        return elegida.household, elegida
