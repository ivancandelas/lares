"""Pantallas de la bandeja."""

from __future__ import annotations

from django.contrib import messages
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
    })


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
