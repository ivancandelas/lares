"""Pantallas de conectores."""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .connectors import run_connector
from .models import Connector
from .registry import registry


def connector_list(request):
    disponibles = [
        {"key": key, "label": runner.label, "description": runner.description}
        for key, runner in sorted(registry.connectors.items())
    ]
    return render(request, "core/connectors.html", {
        "configurados": Connector.objects.all(),
        "disponibles": disponibles,
    })


def connector_new(request, key):
    runner = registry.connectors.get(key)
    if not runner or not runner.form_class:
        raise Http404(f"No hay conector «{key}»")

    form = runner.form_class(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        connector = form.save()
        messages.success(request, f"{connector} configurado. Pruébalo con «Traer ahora».")
        return redirect("core:connectors")

    return render(request, "core/form.html", {
        "form": form, "title": f"Conectar {runner.label}",
        "submit": "Guardar", "cancel_url": "core:connectors",
    })


def connector_edit(request, pk):
    connector = get_object_or_404(Connector, pk=pk)
    runner = registry.connectors.get(connector.key)
    if not runner or not runner.form_class:
        raise Http404(f"No hay conector «{connector.key}»")

    form = runner.form_class(request.POST or None, instance=connector,
                            household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("core:connectors")

    return render(request, "core/form.html", {
        "form": form, "title": str(connector), "submit": "Guardar cambios",
        "cancel_url": "core:connectors",
    })


def connector_run(request, pk):
    connector = get_object_or_404(Connector, pk=pk)
    result = run_connector(connector)

    if result.error:
        messages.success(request, f"{connector}: {result.error}")
    elif result.new:
        messages.success(request, f"{connector}: {result.new} nuevo(s) en la bandeja.")
    else:
        messages.success(request, f"{connector}: nada nuevo ({result.fetched} revisados).")
    return redirect("core:inbox" if result.new else "core:connectors")
