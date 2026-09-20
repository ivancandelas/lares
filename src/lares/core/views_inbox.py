"""Pantallas de la bandeja."""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt

from .forms import DocumentForm
from .models import InboxItem
from .services import ingest
from .services import obligations as obligation_service


def inbox(request):
    if request.method == "POST" and request.FILES:
        nuevos = repetidos = 0
        for archivo in request.FILES.getlist("files"):
            _, es_nuevo = ingest.receive(request.household, archivo)
            nuevos += es_nuevo
            repetidos += not es_nuevo
        if nuevos:
            messages.success(request, f"{nuevos} archivo(s) en la bandeja.")
        if repetidos:
            messages.success(request, f"{repetidos} ya estaban: no se duplicaron.")
        return redirect("core:inbox")

    return render(request, "core/inbox.html", {
        "pendientes": InboxItem.objects.filter(status=InboxItem.Status.NEW),
        "cerrados": InboxItem.objects.exclude(status=InboxItem.Status.NEW)[:10],
    })


def inbox_review(request, pk):
    """El clasificador precarga; la persona confirma. Siempre en ese orden."""
    item = get_object_or_404(InboxItem, pk=pk)

    if request.method == "POST":
        form = DocumentForm(request.POST, household=request.household)
        if form.is_valid():
            documento = form.save()
            ingest.apply(item, documento)
            obligation_service.materialize(request.household)
            messages.success(request, f"«{documento.title}» registrado.")
            return redirect("core:inbox")
    else:
        form = DocumentForm(initial=ingest.initial_document_data(item),
                            household=request.household)

    return render(request, "core/inbox_review.html", {
        "item": item,
        "form": form,
        "propuesta": item.suggestion,
        "vista": _preview_of(item),
    })


def _preview_of(item):
    """El archivo crudo de la bandeja, listo para mirarlo al lado del formulario."""
    import mimetypes

    if not item.file:
        from .services import paperless

        # Referenciado: el archivo está en Paperless y se mira por proxy. Sin
        # esto habría que confirmar a ciegas lo que propone el clasificador.
        return "pdf" if paperless.doc_id(item.external_ref) else ""
    tipo = item.mime_type or mimetypes.guess_type(item.file.name)[0] or ""
    if tipo == "application/pdf":
        return "pdf"
    return "image" if tipo.startswith("image/") else ""


def inbox_reclassify(request, pk):
    propuestas = ingest.reclassify(get_object_or_404(InboxItem, pk=pk))
    if propuestas:
        messages.success(request, f"Ahora parece: {propuestas[0].label}.")
    else:
        messages.success(request, "Sigue sin reconocerse. Dime tú qué es.")
    return redirect("core:inbox")


def inbox_reclassify_all(request):
    result = ingest.reclassify_all(request.household, only_pending=False)
    messages.success(
        request,
        f"{result['reviewed']} revisados, {result['recognised']} reconocidos.",
    )
    return redirect("core:inbox")


def inbox_restore(request, pk):
    """Rescatar algo descartado por error, sin volver a subirlo."""
    item = get_object_or_404(InboxItem, pk=pk)
    item.status = InboxItem.Status.NEW
    item.save(update_fields=["status", "updated_at"])
    messages.success(request, "De vuelta en la bandeja.")
    return redirect("core:inbox")


def inbox_file(request, pk):
    """El archivo crudo de un item, para verlo mientras se revisa.

    Pasa por el manager con ambito de hogar en vez de servirse desde /media/:
    una URL de medios no comprueba nada, asi que cualquiera con sesion podria
    leer el archivo de otra casa conociendo la ruta.
    """
    import mimetypes

    from django.http import FileResponse

    item = get_object_or_404(InboxItem, pk=pk)
    if not item.file:
        return _desde_paperless(item)

    tipo = item.mime_type or mimetypes.guess_type(item.file.name)[0] \
        or "application/octet-stream"
    respuesta = FileResponse(item.file.open("rb"), content_type=tipo)
    respuesta["Content-Disposition"] = f'inline; filename="{item.original_name}"'
    respuesta["Content-Security-Policy"] = "sandbox; frame-ancestors 'self'"
    return respuesta


def inbox_discard(request, pk):
    item = get_object_or_404(InboxItem, pk=pk)
    ingest.discard(item)
    messages.success(request, "Descartado. El archivo se conserva por si acaso.")
    return redirect("core:inbox")


@csrf_exempt
def inbox_share(request):
    """Destino de 'compartir' del móvil.

    Fotografiar un recibo y compartirlo a Lares tiene que ser el camino más
    corto que existe: es la vía que más registros va a generar.
    """
    if request.method != "POST":
        return redirect("core:inbox")

    for archivo in request.FILES.getlist("files") or request.FILES.getlist("file"):
        ingest.receive(request.household, archivo, source=InboxItem.Source.SHARE,
                       note=request.POST.get("title", "")[:300])
    messages.success(request, "Recibido. Revísalo cuando puedas.")
    return redirect("core:inbox")


def _desde_paperless(item):
    """Lo referenciado se mira por proxy: el token no sale de aquí."""
    from django.http import HttpResponse

    from .services import paperless

    if not paperless.doc_id(item.external_ref):
        raise Http404("Esa entrada no tiene archivo.")

    try:
        contenido, tipo = paperless.fetch(item.household, item.external_ref)
    except paperless.Inalcanzable as exc:
        return HttpResponse(
            f"El archivo está en Paperless y ahora no responde ({exc}).",
            content_type="text/plain; charset=utf-8", status=502)

    respuesta = HttpResponse(contenido, content_type=tipo or "application/pdf")
    respuesta["Content-Disposition"] = f'inline; filename="{item.original_name}"'
    respuesta["Content-Security-Policy"] = "sandbox; frame-ancestors 'self'"
    return respuesta
