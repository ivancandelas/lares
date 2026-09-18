from django.shortcuts import render

from .registry import registry
from .services.agenda import week_ahead


def dashboard(request):
    """La pantalla 'Esta semana'.

    No es un tablero de graficas: es la lista de lo que requiere tu atencion.
    Si esta vista no resulta util, el modelo de obligaciones esta mal y hay
    que arreglarlo antes de anadir un solo modulo mas.
    """
    household = getattr(request, "household", None)
    context = {
        "agenda": week_ahead(household) if household else None,
        "widgets": registry.widgets_sorted(),
    }
    return render(request, "core/dashboard.html", context)
