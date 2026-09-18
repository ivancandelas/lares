from django.shortcuts import render
from django.template.loader import render_to_string

from .models import Account, Document, Resource
from .registry import registry
from .services import search as search_service
from .services.agenda import week_ahead
from .services.checks import run_all as run_checks


def dashboard(request):
    """La pantalla 'Esta semana'.

    No es un tablero de graficas: es la lista de lo que requiere tu atencion.
    Muestra tres cosas y en este orden: lo vencido, lo que viene, y los huecos
    que el sistema detecto por su cuenta. Lo tercero es lo que distingue esto
    de una lista de recordatorios.
    """
    household = getattr(request, "household", None)
    context = {
        "agenda": week_ahead(household) if household else None,
        "findings": run_checks(household) if household else [],
        "widgets": _render_widgets(household, request) if household else [],
    }
    return render(request, "core/dashboard.html", context)


def holdings(request):
    """Todo lo que tienes, en una pantalla.

    Sale de una sola consulta sobre Resource: por herencia multi-tabla, cada
    modulo aporta lo suyo -coches, tarjetas, inmuebles- sin que esta vista
    sepa que existen.
    """
    recursos = Resource.objects.filter(status=Resource.Status.ACTIVE)

    grupos, valor_total = {}, 0
    for recurso in recursos:
        etiqueta = _kind_label(recurso.kind)
        grupos.setdefault(etiqueta, []).append(recurso)
        valor_total += recurso.current_value or recurso.purchase_amount or 0

    deuda = sum(
        c.balance for c in Account.objects.filter(
            type=Account.Type.LIABILITY, is_active=True
        )
    )
    return render(request, "core/holdings.html", {
        "grupos": grupos,
        "total": len(recursos),
        "valor_total": valor_total,
        "deuda": deuda,
        "neto": valor_total - deuda,
    })


def documents(request):
    docs = Document.objects.filter(archived_at__isnull=True)
    return render(request, "core/documents.html", {
        "vencen": docs.filter(expires_on__isnull=False).order_by("expires_on"),
        "sin_vencimiento": docs.filter(expires_on__isnull=True),
    })


def _kind_label(kind: str) -> str:
    model = registry.resource_kinds.get(kind)
    if model is None:
        return kind or "Otros"
    return str(model._meta.verbose_name_plural).capitalize()


def search(request):
    query = request.GET.get("q", "")
    household = getattr(request, "household", None)
    return render(request, "core/search.html", {
        "query": query,
        "hits": search_service.search(household, query) if household else [],
    })


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
