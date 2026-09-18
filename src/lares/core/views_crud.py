"""Pantallas de alta y edicion.

Las de recurso son genericas: el modulo registra su formulario y el nucleo pone
el alta, la edicion y la ficha. Un CRUD escrito por modulo es la forma mas
rapida de que cada pantalla acabe pareciendose a otra cosa.
"""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from . import related
from .forms import (
    AccountForm,
    DisposalForm,
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
        "enlaces": registry.links_for(obj),
        "prestado_a": related.borrower_of(obj),
        "facts": obj.facts(),
        "documentos": documentos,
        "obligaciones": pendientes,
        "editable": obj.kind in registry.resource_forms,
        "tabs": _render_tabs(obj, request),
    })


def _render_tabs(obj, request) -> list:
    """Bloques que aportan los módulos. Uno roto no tumba la ficha entera."""
    from django.template.loader import render_to_string

    salida = []
    for tab in registry.tabs_for(obj.kind):
        try:
            datos = tab.provider(obj) if tab.provider else {}
            html = render_to_string(tab.template, datos, request=request)
        except Exception:
            continue
        salida.append({"key": tab.key, "label": tab.label, "html": html})
    return salida


# ---------------------------------------------------------------------------
# Personas y contactos
# ---------------------------------------------------------------------------


def resource_dispose(request, pk):
    """Dar de baja: vendido, perdido, robado, regalado."""
    base = get_object_or_404(Resource, pk=pk)
    obj = base.as_concrete()

    form = DisposalForm(request.POST or None, instance=obj, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{obj}: {obj.disposal_line.lower()}.")
        return redirect("core:resource-detail", pk=obj.pk)

    return render(request, "core/form.html", {
        "form": form, "title": f"Dar de baja: {obj}", "submit": "Dar de baja",
        "cancel_url": "core:resource-detail", "cancel_arg": obj.pk,
    })


def resource_verify(request, pk):
    """«Sí, sigo teniéndolo.»

    Es lo que evita que el inventario envejezca hasta volverse ficción, que es
    el destino de todos los inventarios domésticos.
    """
    import datetime as dt

    base = get_object_or_404(Resource, pk=pk)
    Resource.objects.filter(pk=base.pk).update(verified_on=dt.date.today())
    messages.success(request, "Comprobado. Vuelvo a preguntarte dentro de un año.")
    return redirect("core:resource-detail", pk=base.pk)


def resource_restore(request, pk):
    """Deshacer una baja puesta por error."""
    base = get_object_or_404(Resource, pk=pk)
    obj = base.as_concrete()
    obj.status = Resource.Status.ACTIVE
    obj.disposal_reason = ""
    obj.disposed_on = None
    obj.disposal_amount = None
    obj.save()
    _refresh(request.household)
    messages.success(request, "De vuelta en tu patrimonio.")
    return redirect("core:resource-detail", pk=obj.pk)


def party_list(request):
    return render(request, "core/parties.html", {
        "personas": Party.objects.filter(kind=Party.Kind.PERSON),
        "organizaciones": Party.objects.filter(kind=Party.Kind.ORGANIZATION),
    })


def party_detail(request, pk):
    """La ficha de una persona u organización, con lo que cuelga de ella."""
    party = get_object_or_404(Party, pk=pk)
    return render(request, "core/party_detail.html", {
        "party": party,
        "enlaces": registry.links_for(party),
        "prestados": related.lent_to(party),
    })


def resource_lend(request, pk):
    """Prestar una cosa: «¿a quién le presté el taladro?»."""
    from django.contrib.contenttypes.models import ContentType

    base = get_object_or_404(Resource, pk=pk)
    obj = base.as_concrete()

    if request.method == "POST" and request.POST.get("party"):
        destinatario = get_object_or_404(Party, pk=request.POST["party"])
        Link.objects.get_or_create(
            household=request.household,
            source_type=ContentType.objects.get_for_model(obj.__class__),
            source_id=obj.pk, role=related.LENT_TO,
            target_type=ContentType.objects.get_for_model(Party),
            target_id=destinatario.pk, valid_to=None,
            defaults={"valid_from": dt.date.today()},
        )
        messages.success(request, f"{obj} está con {destinatario}.")
        return redirect("core:resource-detail", pk=obj.pk)

    return render(request, "core/lend.html", {
        "obj": obj,
        "personas": Party.objects.filter(kind=Party.Kind.PERSON),
    })


def resource_return(request, pk):
    from django.contrib.contenttypes.models import ContentType

    base = get_object_or_404(Resource, pk=pk)
    obj = base.as_concrete()
    # No se borra la arista: se cierra. El préstamo pasado es historial.
    Link.objects.filter(
        role=related.LENT_TO,
        source_type=ContentType.objects.get_for_model(obj.__class__),
        source_id=obj.pk, valid_to__isnull=True,
    ).update(valid_to=dt.date.today())
    messages.success(request, f"{obj} está de vuelta.")
    return redirect("core:resource-detail", pk=obj.pk)


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
    """Alta de documento.

    Acepta `?para=<uuid>` para llegar desde la ficha de un coche o una casa con
    el destino ya elegido: adjuntar la factura de algo es lo que más veces se
    hace, y no debería costar tres clics de navegación.
    """
    destino = request.GET.get("para")
    inicial = {"attach_to": destino} if destino else {}

    form = DocumentForm(request.POST or None, request.FILES or None,
                        initial=inicial, household=request.household)
    if request.method == "POST" and form.is_valid():
        doc = form.save()
        _refresh(request.household)
        messages.success(request, f"«{doc.title}» guardado.")
        adjuntado = form.cleaned_data.get("attach_to")
        if adjuntado:
            return redirect("core:resource-detail", pk=adjuntado.pk)
        return redirect("core:documents")

    titulo = "Nuevo documento"
    if destino:
        recurso = Resource.objects.filter(pk=destino).first()
        if recurso:
            titulo = f"Documento de {recurso.name}"

    return render(request, "core/form.html", {
        "form": form, "title": titulo, "submit": "Guardar",
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
