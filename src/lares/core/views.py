from django.shortcuts import render
from django.template.loader import render_to_string

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
        "widgets": _render_widgets(household, request) if household else [],
    }
    return render(request, "core/dashboard.html", context)


def _render_widgets(household, request):
    """Cada modulo aporta su tarjeta: el nucleo solo la coloca.

    Un widget roto no debe tumbar el tablero entero, asi que se aisla.
    """
    rendered = []
    for widget in registry.widgets_sorted():
        try:
            data = widget.provider(household) or {}
            html = render_to_string(widget.template, data, request=request)
        except Exception:
            continue
        rendered.append({"key": widget.key, "label": widget.label, "size": widget.size,
                         "html": html})
    return rendered
