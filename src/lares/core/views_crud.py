"""Pantallas de alta y edicion.

Las de recurso son genericas: el modulo registra su formulario y el nucleo pone
el alta, la edicion y la ficha. Un CRUD escrito por modulo es la forma mas
rapida de que cada pantalla acabe pareciendose a otra cosa.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    AccountForm,
    DocumentForm,
    ExpenseForm,
    LocationForm,
    ObligationRuleForm,
    PartyForm,
)
from .models import Document, Link, Obligation, ObligationRule, Party, Resource
from .registry import registry
from .services import obligations as obligation_service


def _refresh(household):
    """Materializa tras guardar.

    Si registras un coche y sus vencimientos no aparecen hasta mañana, el
    sistema parece roto aunque no lo esté.
    """
    try:
        obligation_service.materialize(household)
    except Exception:  # noqa: BLE001 - guardar nunca debe fallar por esto
        pass


# ---------------------------------------------------------------------------
# Hub de alta
# ---------------------------------------------------------------------------


def add_index(request):
    tipos = [
        {"url": "core:resource-new", "arg": kind,
         "label": str(model._meta.verbose_name).capitalize()}
        for kind, model in sorted(registry.resource_kinds.items())
        if kind in registry.resource_forms
    ]
    return render(request, "core/add_index.html", {"tipos": tipos})


# ---------------------------------------------------------------------------
# Recursos (los aportan los modulos)
# ---------------------------------------------------------------------------


def resource_new(request, kind):
    form_class = registry.resource_forms.get(kind)
    if not form_class:
        raise Http404(f"No hay formulario para «{kind}»")

    form = form_class(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _refresh(request.household)
        messages.success(request, f"{obj} registrado.")
        return redirect("core:resource-detail", pk=obj.pk)

    model = registry.resource_kinds[kind]
    return render(request, "core/form.html", {
        "form": form,
        "title": f"Nuevo: {model._meta.verbose_name}",
        "submit": "Guardar",
        "cancel_url": "core:holdings",
    })


def resource_edit(request, pk):
    base = get_object_or_404(Resource, pk=pk)
    obj = base.as_concrete()
    form_class = registry.resource_forms.get(obj.kind)
    if not form_class:
        raise Http404(f"No hay formulario para «{obj.kind}»")

    form = form_class(request.POST or None, instance=obj, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        _refresh(request.household)
        messages.success(request, "Cambios guardados.")
        return redirect("core:resource-detail", pk=obj.pk)

    return render(request, "core/form.html", {
        "form": form, "title": str(obj), "submit": "Guardar cambios",
        "cancel_url": "core:resource-detail", "cancel_arg": obj.pk,
    })


def resource_detail(request, pk):
    from django.contrib.contenttypes.models import ContentType

    base = get_object_or_404(Resource, pk=pk)
    obj = base.as_concrete()
    ctype = ContentType.objects.get_for_model(obj.__class__)

    documentos = Document.objects.filter(
        pk__in=Link.objects.filter(
            role="documents", target_type=ctype, target_id=obj.pk
        ).values_list("source_id", flat=True)
    )
    pendientes = Obligation.objects.filter(
        subject_type=ctype, subject_id=obj.pk,
        status__in=[Obligation.Status.PENDING, Obligation.Status.OVERDUE],
    )
    return render(request, "core/resource_detail.html", {
        "obj": obj,
        "facts": obj.facts(),
        "documentos": documentos,
        "obligaciones": pendientes,
        "editable": obj.kind in registry.resource_forms,
        "tabs": registry.tabs_for(obj.kind),
    })


# ---------------------------------------------------------------------------
# Personas y contactos
# ---------------------------------------------------------------------------


def party_list(request):
    return render(request, "core/parties.html", {
        "personas": Party.objects.filter(kind=Party.Kind.PERSON),
        "organizaciones": Party.objects.filter(kind=Party.Kind.ORGANIZATION),
    })


def party_new(request):
    return _simple_form(request, PartyForm, "Nueva persona u organización",
                        "core:parties")


def party_edit(request, pk):
    return _simple_form(request, PartyForm, "Editar", "core:parties",
                        instance=get_object_or_404(Party, pk=pk))


# ---------------------------------------------------------------------------
# Documentos, reglas, cuentas, gastos, ubicaciones
# ---------------------------------------------------------------------------


def document_new(request):
    form = DocumentForm(request.POST or None, request.FILES or None,
                        household=request.household)
    if request.method == "POST" and form.is_valid():
        doc = form.save()
        _refresh(request.household)
        messages.success(request, f"«{doc.title}» guardado.")
        return redirect("core:documents")
    return render(request, "core/form.html", {
        "form": form, "title": "Nuevo documento", "submit": "Guardar",
        "cancel_url": "core:documents", "multipart": True,
    })


def document_edit(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    form = DocumentForm(request.POST or None, request.FILES or None,
                        instance=doc, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        _refresh(request.household)
        messages.success(request, "Cambios guardados.")
        return redirect("core:documents")
    return render(request, "core/form.html", {
        "form": form, "title": doc.title, "submit": "Guardar cambios",
        "cancel_url": "core:documents", "multipart": True,
    })


def rule_list(request):
    return render(request, "core/rules.html", {
        "reglas": ObligationRule.objects.all(),
    })


def rule_new(request):
    form = ObligationRuleForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        rule = form.save()
        _refresh(request.household)
        messages.success(request, f"«{rule.label}» quedó programado.")
        return redirect("core:rules")
    return render(request, "core/form.html", {
        "form": form, "title": "Nuevo pago o trámite recurrente",
        "submit": "Programar", "cancel_url": "core:rules",
    })


def rule_toggle(request, pk):
    rule = get_object_or_404(ObligationRule, pk=pk)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active", "updated_at"])
    _refresh(request.household)
    return redirect("core:rules")


def account_new(request):
    return _simple_form(request, AccountForm, "Nueva cuenta", "finance:accounts")


def location_new(request):
    return _simple_form(request, LocationForm, "Nueva ubicación", "core:holdings")


def expense_new(request):
    form = ExpenseForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        entry = form.save()
        messages.success(request, f"«{entry.description}» registrado.")
        return redirect("finance:accounts")
    return render(request, "core/form.html", {
        "form": form, "title": "Registrar un gasto", "submit": "Registrar",
        "cancel_url": "finance:accounts",
    })


def _simple_form(request, form_class, title, cancel_url, instance=None):
    form = form_class(request.POST or None, instance=instance,
                      household=request.household)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"{obj} guardado.")
        return redirect(cancel_url)
    return render(request, "core/form.html", {
        "form": form, "title": title, "submit": "Guardar", "cancel_url": cancel_url,
    })
