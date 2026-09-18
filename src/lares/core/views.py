from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from .models import Account, Document, Resource
from .registry import registry
from .services import search as search_service
from .services.agenda import week_ahead
from .services.completeness import assess


def dashboard(request):
    """La pantalla 'Esta semana'.

    No es un tablero de graficas: es la lista de lo que requiere tu atencion.
    Muestra tres cosas y en este orden: lo vencido, lo que viene, y los huecos
    que el sistema detecto por su cuenta. Lo tercero es lo que distingue esto
    de una lista de recordatorios.
    """
    household = getattr(request, "household", None)
    completitud = assess(household) if household else None
    context = {
        "agenda": week_ahead(household) if household else None,
        # Los huecos ya vienen calculados dentro de la valoración: recalcularlos
        # recorrería todo el inventario una segunda vez por cada carga.
        "findings": completitud["gaps"] if completitud else [],
        "completeness": completitud,
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
    ajenos = []
    for recurso in recursos:
        concreto = recurso.as_concrete()
        etiqueta = _kind_label(recurso.kind)
        grupos.setdefault(etiqueta, []).append(recurso)
        if concreto.counts_as_asset:
            valor_total += recurso.current_value or recurso.purchase_amount or 0
        else:
            # Lo que administras pero no es tuyo: cuenta como coste, no como bien.
            ajenos.append(recurso)

    deuda = sum(
        c.balance for c in Account.objects.filter(
            type=Account.Type.LIABILITY, is_active=True
        )
    )
    idos = Resource.objects.filter(status=Resource.Status.DISPOSED).order_by("-disposed_on")
    return render(request, "core/holdings.html", {
        "grupos": grupos,
        "ajenos": ajenos,
        "idos": idos[:20],
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


def onboarding(request):
    """Qué falta y por dónde seguir.

    El onboarding más honesto no es un tutorial: es la lista de lo que este
    hogar todavía no tiene, ordenada por lo que más cambia el resultado.
    """
    household = getattr(request, "household", None)
    return render(request, "core/onboarding.html", {
        "completeness": assess(household) if household else None,
    })


@login_not_required
def manifest(request):
    """Manifiesto de la PWA.

    El share_target es lo que hace que compartir una foto desde el móvil acabe
    en la bandeja sin pasar por ningún menú.
    """
    return JsonResponse({
        "name": settings.PRODUCT_NAME,
        "short_name": settings.PRODUCT_NAME,
        "description": settings.PRODUCT_TAGLINE,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#FBFBF9",
        "theme_color": "#17201C",
        "lang": "es",
        "icons": [],
        "share_target": {
            "action": reverse("core:inbox-share"),
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {
                "title": "title",
                "text": "text",
                "files": [{"name": "files", "accept": ["image/*", "application/pdf",
                                                       "text/xml", "application/xml"]}],
            },
        },
    }, content_type="application/manifest+json")


@login_not_required
def service_worker(request):
    """Mínimo imprescindible: existir para que la app se pueda instalar.

    No cachea nada todavía. Un service worker que cachea mal es peor que no
    tenerlo: sirve datos viejos de un sistema cuyo valor es estar al día.
    """
    return HttpResponse(
        "self.addEventListener('install', () => self.skipWaiting());\n"
        "self.addEventListener('activate', e => e.waitUntil(clients.claim()));\n"
        "self.addEventListener('fetch', () => {});\n",
        content_type="application/javascript",
    )


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
