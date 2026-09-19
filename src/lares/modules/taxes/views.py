import datetime as dt

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import DeductionForm, FilingForm, TaxProfileForm, WithholdingForm
from .models import Deduction, Filing, TaxProfile, Withholding
from .package import build
from .services import summarize


def overview(request):
    """Qué te toca, cuánto llevas y qué falta por revisar."""
    ano = int(request.GET.get("ano") or dt.date.today().year)
    perfiles = list(TaxProfile.objects.filter(is_active=True)
                    .select_related("taxpayer"))
    resumenes = [summarize(request.household, p, ano) for p in perfiles]

    return render(request, "taxes/overview.html", {
        "ano": ano,
        "anos": range(dt.date.today().year, dt.date.today().year - 5, -1),
        "resumenes": resumenes,
        "declaraciones": Filing.objects.select_related("profile__taxpayer")[:12],
        "sin_perfil": not perfiles,
    })


def profile_detail(request, pk):
    perfil = get_object_or_404(TaxProfile, pk=pk)
    ano = int(request.GET.get("ano") or dt.date.today().year)
    return render(request, "taxes/profile.html", {
        "perfil": perfil,
        "ano": ano,
        "anos": range(dt.date.today().year, dt.date.today().year - 5, -1),
        "resumen": summarize(request.household, perfil, ano),
        "deducciones": Deduction.objects.filter(profile=perfil, date__year=ano)
                                        .select_related("document"),
        "retenciones": Withholding.objects.filter(profile=perfil, date__year=ano)
                                          .select_related("payer"),
        "declaraciones": Filing.objects.filter(profile=perfil),
    })


def package(request, pk):
    """El ZIP para el contador."""
    perfil = get_object_or_404(TaxProfile, pk=pk)
    ano = int(request.GET.get("ano") or dt.date.today().year)
    nombre, contenido = build(request.household, perfil, ano)

    respuesta = HttpResponse(contenido, content_type="application/zip")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _alta(request, form_class, titulo, submit="Guardar", volver="taxes:overview",
          instancia=None, inicial=None):
    form = form_class(request.POST or None, instance=instancia,
                      initial=inicial or {}, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{titulo}: guardado.")
        return redirect(volver)
    return render(request, "core/form.html", {
        "form": form, "title": titulo, "submit": submit,
        "cancel_url": volver,
    })


def profile_new(request):
    return _alta(request, TaxProfileForm, "Nuevo perfil fiscal", "Crear")


def profile_edit(request, pk):
    perfil = get_object_or_404(TaxProfile, pk=pk)
    return _alta(request, TaxProfileForm, str(perfil), "Guardar cambios",
                 instancia=perfil)


def deduction_new(request):
    inicial = {}
    # Llegar desde un documento es el camino corto: marcar una factura que ya
    # esta dentro no deberia obligar a teclear su importe otra vez.
    if documento_id := request.GET.get("documento"):
        from lares.core.models import Document

        documento = Document.objects.filter(pk=documento_id).first()
        if documento:
            inicial = {"document": documento.pk, "amount": documento.amount,
                       "date": documento.issued_on, "description": documento.title}
    return _alta(request, DeductionForm, "Marcar como deducible", "Marcar",
                 inicial=inicial)


def deduction_edit(request, pk):
    deduccion = get_object_or_404(Deduction, pk=pk)
    return _alta(request, DeductionForm, str(deduccion), "Guardar cambios",
                 instancia=deduccion)


def deduction_delete(request, pk):
    deduccion = get_object_or_404(Deduction, pk=pk)
    perfil_id = deduccion.profile_id
    deduccion.delete()
    messages.success(request, "Ya no se deduce.")
    return redirect("taxes:profile", pk=perfil_id)


def withholding_new(request):
    return _alta(request, WithholdingForm, "Registrar una retención", "Registrar")


def filing_new(request):
    return _alta(request, FilingForm, "Registrar una declaración", "Registrar")


def filing_edit(request, pk):
    declaracion = get_object_or_404(Filing, pk=pk)
    return _alta(request, FilingForm, str(declaracion), "Guardar cambios",
                 instancia=declaracion)
