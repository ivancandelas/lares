"""API HTTP de Lares.

Django puro y sin dependencias: seis endpoints no justifican un framework, y
asi se controla con exactitud como se autentica y como se exime del middleware
que exige sesion. Si la superficie crece, el sitio natural para cambiar es este
archivo.

Autenticacion: cabecera `X-Lares-Key`. Las lecturas admiten ademas la sesion del
navegador; las escrituras exigen llave, para no abrir un hueco de CSRF.
"""

from __future__ import annotations

import datetime as dt
import json

from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ApiKey, Document, Obligation, Resource, Webhook
from .models.integrations import _hash
from .scoping import use_household
from .services import checks as checks_service
from .services import search as search_service
from .services.agenda import week_ahead


def endpoint(write: bool = False):
    """Autenticacion y alcance de hogar para una vista de la API."""
    def decorator(view):
        @csrf_exempt
        @login_not_required
        def wrapper(request, *args, **kwargs):
            household = _household_from_key(request)
            if household is None:
                if write:
                    return _error("Esta operación necesita una llave de API.", 401)
                household = _household_from_session(request)
            if household is None:
                return _error("Falta la cabecera X-Lares-Key.", 401)

            with use_household(household):
                request.household = household
                return view(request, *args, **kwargs)
        wrapper.__name__ = view.__name__
        return wrapper
    return decorator


def _household_from_key(request):
    token = request.headers.get("X-Lares-Key", "")
    if "." not in token:
        return None
    prefix = token.split(".", 1)[0]
    key = ApiKey.all_objects.filter(prefix=prefix, revoked_at__isnull=True).first()
    if not key:
        return None
    import secrets as _secrets
    if not _secrets.compare_digest(key.key_hash, _hash(token)):
        return None
    ApiKey.all_objects.filter(pk=key.pk).update(last_used_at=timezone.now())
    return key.household


def _household_from_session(request):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return getattr(request, "household", None)
    return None


def _error(message: str, status: int):
    return JsonResponse({"error": message}, status=status)


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


@endpoint()
def agenda(request):
    data = _visible(week_ahead(request.household), request)
    return JsonResponse({
        "today": data["today"].isoformat(),
        "overdue": [_obligation(o) for o in data["overdue"]],
        "this_week": [_obligation(o) for o in data["this_week"]],
        "later": [_obligation(o) for o in data["later"]],
        "total_amount": float(data["total_amount"] or 0),
    })


@endpoint()
def obligations(request):
    qs = Obligation.objects.all()
    if status := request.GET.get("status"):
        qs = qs.filter(status=status)
    if before := _date(request.GET.get("due_before")):
        qs = qs.filter(due_on__lte=before)
    from .permissions import visible_obligations

    lista = visible_obligations(qs[:200], getattr(request, "membership", None)) \
        if getattr(request, "membership", None) else list(qs[:200])
    return JsonResponse({"results": [_obligation(o) for o in lista]})


def _visible(data: dict, request) -> dict:
    """La API devuelve lo mismo que la pantalla, ni más ni menos.

    Aceptar la sesión del navegador y no medir los ámbitos convertiría
    `/api/v1/agenda` en la puerta de atrás que ya se cerró una vez.
    """
    from .permissions import visible_obligations

    membership = getattr(request, "membership", None)
    if membership is None:
        return data
    salida = dict(data)
    for clave in ("overdue", "this_week", "later"):
        salida[clave] = visible_obligations(data[clave], membership)
    salida["total_amount"] = sum(
        o.amount or 0 for clave in ("overdue", "this_week", "later")
        for o in salida[clave]
    )
    return salida


@endpoint()
def resources(request):
    qs = Resource.objects.filter(status=Resource.Status.ACTIVE)
    if kind := request.GET.get("kind"):
        qs = qs.filter(kind=kind)
    return JsonResponse({"results": [{
        "id": str(r.pk), "kind": r.kind, "name": r.name,
        "owner": str(r.owner) if r.owner else None,
        "value": float(r.current_value) if r.current_value else None,
        "currency": r.currency or None,
    } for r in qs[:200]]})


@endpoint()
def documents(request):
    qs = Document.objects.filter(archived_at__isnull=True)
    return JsonResponse({"results": [{
        "id": str(d.pk), "title": d.title, "type": d.doc_type or None,
        "expires_on": d.expires_on.isoformat() if d.expires_on else None,
    } for d in qs[:200]]})


@endpoint()
def gaps(request):
    """Lo que el sistema detecta que falta. El endpoint mas util para un agente."""
    return JsonResponse({"results": [{
        "check": f.check, "title": f.title, "detail": f.detail,
        "severity": f.severity,
    } for f in checks_service.run_all(request.household)]})


@endpoint()
def search(request):
    hits = search_service.search(request.household, request.GET.get("q", ""))
    return JsonResponse({"results": [{
        "kind": h.kind, "label": h.label, "title": h.title, "subtitle": h.subtitle,
    } for h in hits]})


# ---------------------------------------------------------------------------
# Escrituras
# ---------------------------------------------------------------------------


@endpoint(write=True)
def complete_obligation(request, pk):
    if request.method != "POST":
        return _error("Usa POST.", 405)
    obligation = Obligation.objects.filter(pk=pk).first()
    if not obligation:
        return _error("No existe esa obligación.", 404)

    obligation.status = Obligation.Status.DONE
    obligation.completed_at = timezone.now()
    obligation.save(update_fields=["status", "completed_at", "updated_at"])
    return JsonResponse(_obligation(obligation))


@endpoint(write=True)
def webhooks(request):
    if request.method == "GET":
        return JsonResponse({"results": [{
            "id": str(w.pk), "url": w.url, "events": w.events, "active": w.is_active,
        } for w in Webhook.objects.all()]})

    if request.method != "POST":
        return _error("Usa GET o POST.", 405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return _error("El cuerpo no es JSON válido.", 400)
    if not payload.get("url"):
        return _error("Falta 'url'.", 400)

    hook = Webhook.objects.create(
        household=request.household,
        url=payload["url"],
        events=payload.get("events") or ["*"],
    )
    # El secreto se muestra una sola vez: con él se verifica la firma.
    return JsonResponse({"id": str(hook.pk), "url": hook.url, "events": hook.events,
                         "secret": hook.secret}, status=201)


# ---------------------------------------------------------------------------


def _obligation(o) -> dict:
    return {
        "id": str(o.pk),
        "title": o.title,
        "due_on": o.due_on.isoformat(),
        "days_left": o.days_left,
        "status": o.status,
        "severity": o.severity,
        "urgency": o.urgency,
        "amount": float(o.amount) if o.amount else None,
        "currency": o.currency or None,
        "source": o.source,
    }


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None
