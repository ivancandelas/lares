import datetime as dt

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
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
        "findings": _visibles(completitud["gaps"] if completitud else [],
                              request),
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

    # El cálculo consolidado lo aporta el módulo de dinero, si está instalado:
    # solo él sabe que el saldo del banco suma, que un préstamo recibido es
    # deuda y que uno concedido ya cuenta como bien.
    consolidado = _consolidado(request.household)
    if consolidado:
        valor_total = consolidado["assets"]
        deuda = consolidado["liabilities"]
    else:
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
        "consolidado": consolidado,
    })


def _visibles(findings, request):
    """Los huecos de lo que esta persona ve.

    Un hueco lleva el titulo dentro -"Tarjeta ****9876 sin estado de cuenta"-,
    asi que filtrarlos no es cosmetica: es la misma fuga que el menu.
    """
    from .permissions import visible_scopes

    membership = getattr(request, "membership", None)
    if membership is None:
        return findings
    permitidos = visible_scopes(membership)
    if permitidos is None:
        return findings
    return [f for f in findings if f.check.split(".")[0] in permitidos]


def _consolidado(household):
    """El patrimonio consolidado, si algun modulo sabe calcularlo.

    El nucleo no importa el modulo de dinero: se lo pide al registro. Solo ese
    modulo sabe que el saldo del banco suma, que un prestamo recibido es deuda
    y que uno concedido ya cuenta como bien.
    """
    return registry.calculate("net_worth", household)


def owed(request):
    """Quién te debe y a quién le debes, en una sola pantalla.

    No hay tabla de cuentas por cobrar ni por pagar. Lo que se debe ya esta
    registrado donde ocurre -el prestamo sabe cuanto falta, el contrato sabe
    que meses no llegaron, la tarjeta sabe su saldo- y copiarlo a una tabla
    aparte crearia dos verdades que se separan al primer abono.

    Lo unico que faltaba era mirarlo junto, porque las dos preguntas que
    importan -cuanto me deben, cuanto debo- son las unicas que ningun modulo
    puede responder solo.
    """
    partidas = registry.owed_all(request.household)
    # Lo vencido primero; despues lo que tiene fecha; al final lo que no la
    # tiene, que no es menos importante pero no compite por el mismo dia.
    partidas.sort(key=lambda o: (o.due_on is None, o.due_on or dt.date.max,
                                 -float(o.amount or 0)))
    cobrar = [o for o in partidas if o.is_incoming]
    pagar = [o for o in partidas if not o.is_incoming]

    return render(request, "core/owed.html", {
        "cobrar": cobrar,
        "pagar": pagar,
        "total_cobrar": (cobran := sum(o.amount or 0 for o in cobrar)),
        "total_pagar": (pagan := sum(o.amount or 0 for o in pagar)),
        "neto": cobran - pagan,
        "vencidas": [o for o in partidas if o.is_overdue],
    })


def documents(request):
    docs = Document.objects.filter(archived_at__isnull=True)
    return render(request, "core/documents.html", {
        "vencen": docs.filter(expires_on__isnull=False).order_by("expires_on"),
        "sin_vencimiento": docs.filter(expires_on__isnull=True),
    })


@login_not_required
def calendar_feed(request, token):
    """El feed suscribible. Sin sesión: lo consume un calendario, no un navegador.

    El token va en la URL porque así lo exige cualquier cliente de calendario.
    Es un secreto débil a conciencia: se puede rotar y solo expone títulos y
    fechas, nunca números de póliza, documentos ni saldos.
    """
    from .models import Household
    from .services import calendar as cal

    household = Household.objects.filter(calendar_token=token).first()
    if not household or not token:
        raise Http404("Ese calendario no existe o se revocó.")

    prefijo = request.GET.get("de", "")
    discreto = request.GET.get("discreto") in ("1", "si", "true")
    contenido = cal.feed(household, source_prefix=prefijo, discreet=discreto)
    respuesta = HttpResponse(contenido, content_type="text/calendar; charset=utf-8")
    respuesta["Content-Disposition"] = 'inline; filename="lares.ics"'
    return respuesta


def obligation_ics(request, pk):
    """«Añadir al calendario» de una obligación suelta."""
    from .models import Obligation
    from .services import calendar as cal

    obligation = get_object_or_404(Obligation, pk=pk)
    respuesta = HttpResponse(cal.single(obligation),
                             content_type="text/calendar; charset=utf-8")
    respuesta["Content-Disposition"] = 'attachment; filename="vencimiento.ics"'
    return respuesta


def calendar_settings(request):
    """Dónde copiar la dirección del feed y cómo revocarla."""
    household = request.household
    if request.method == "POST":
        household.rotate_calendar_token()
        messages.success(request, "Dirección nueva. La anterior dejó de funcionar.")
        return redirect("core:calendar-settings")

    if not household.calendar_token:
        household.rotate_calendar_token()

    url = request.build_absolute_uri(
        reverse("core:calendar-feed", args=[household.calendar_token])
    )
    return render(request, "core/calendar.html", {
        "url": url,
        "webcal": url.replace("http://", "webcal://").replace("https://", "webcal://"),
        "areas": sorted({o for o in registry.obligation_providers}),
    })


PREVISUALIZABLES = {
    "application/pdf": "pdf",
    "image/jpeg": "image", "image/png": "image", "image/gif": "image",
    "image/webp": "image", "image/heic": "image",
}


def document_preview(request, pk):
    """Sirve un documento para verlo, sin descargarlo.

    Bajar un archivo para comprobar si es el que buscabas deja copias por todas
    partes y rompe el hilo de lo que estabas haciendo.

    Lo que importa aqui no es el visor -el navegador ya sabe mostrar PDF e
    imagenes- sino que la consulta pase por el manager con ambito de hogar: un
    documento de una casa no debe abrirse desde otra ni conociendo su
    identificador.
    """
    from django.http import FileResponse

    from .models import Document

    documento = get_object_or_404(Document, pk=pk)
    if not documento.file:
        raise Http404("Ese documento no tiene archivo.")

    respuesta = FileResponse(documento.file.open("rb"))
    tipo = documento.mime_type or _guess_type(documento.file.name)
    respuesta["Content-Type"] = tipo
    # inline: el navegador lo muestra en vez de descargarlo.
    respuesta["Content-Disposition"] = f'inline; filename="{documento.file.name.split("/")[-1]}"'
    # Un documento ajeno no debe poder incrustarse desde otro sitio.
    respuesta["X-Frame-Options"] = "SAMEORIGIN"
    respuesta["Content-Security-Policy"] = "sandbox; frame-ancestors 'self'"
    return respuesta


def _guess_type(nombre: str) -> str:
    import mimetypes

    return mimetypes.guess_type(nombre)[0] or "application/octet-stream"


def preview_kind(documento) -> str:
    """Cómo se puede mostrar: incrustado, como imagen, o de ninguna manera."""
    if not documento.file:
        return ""
    tipo = documento.mime_type or _guess_type(documento.file.name)
    return PREVISUALIZABLES.get(tipo, "")


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

    Un widget roto no debe tumbar el tablero entero, asi que se aisla. Y los
    de un modulo que esta persona no ve no se pintan: el tablero es la primera
    pantalla y seria la fuga mas facil de todas.
    """
    from .permissions import visible_scopes

    permitidos = visible_scopes(getattr(request, "membership", None)) \
        if getattr(request, "membership", None) else None

    rendered = []
    for widget in registry.widgets_sorted():
        if permitidos is not None and widget.key.split(".")[0] not in permitidos:
            continue
        try:
            data = widget.provider(household) or {}
            html = render_to_string(widget.template, data, request=request)
        except Exception:
            continue
        rendered.append({"key": widget.key, "label": widget.label, "size": widget.size,
                         "html": html})
    return rendered


def responsibilities_view(request):
    """Quién se encarga de qué.

    La pregunta que contesta no es «qué hay que hacer» -eso es el tablero- sino
    **de quién es**. Por eso lo primero que se ve es el reparto, y lo segundo
    lo que no lleva nadie: una obligación de la que no se encarga nadie es la
    que se pasa.
    """
    from .services import responsibilities

    datos = responsibilities.split(request.household)
    return render(request, "core/responsibilities.html", datos)
