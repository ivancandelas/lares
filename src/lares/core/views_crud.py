"""Pantallas de alta y edicion.

Las de recurso son genericas: el modulo registra su formulario y el nucleo pone
el alta, la edicion y la ficha. Un CRUD escrito por modulo es la forma mas
rapida de que cada pantalla acabe pareciendose a otra cosa.
"""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import related
from .forms import (
    AccountForm,
    DisposalForm,
    DocumentForm,
    ExpenseForm,
    IncomeEntryForm,
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

    from .services import responsibilities

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
    from .views import preview_kind

    return render(request, "core/resource_detail.html", {
        "obj": obj,
        "documentos_vista": [
            {"doc": d, "kind": preview_kind(d)} for d in documentos
        ],
        "enlaces": registry.links_for(obj),
        "prestado_a": related.borrower_of(obj),
        "responsable": responsibilities.responsible_of(obj),
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


def party_detail(request, pk):
    """La ficha de una persona u organización, con lo que cuelga de ella."""
    party = get_object_or_404(Party, pk=pk)
    from .models.tagging import tags_of

    return render(request, "core/party_detail.html", {
        "party": party,
        "etiquetas": tags_of(party),
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


def resource_care(request, pk):
    """Quién se encarga de esto. Vacío lo deja sin dueño, que es un dato."""
    from .services import responsibilities

    base = get_object_or_404(Resource, pk=pk)
    obj = base.as_concrete()

    if request.method == "POST":
        elegido = request.POST.get("party")
        persona = get_object_or_404(Party, pk=elegido) if elegido else None
        responsibilities.set_responsible(request.household, obj, persona)
        messages.success(
            request,
            f"{obj} es cosa de {persona}." if persona
            else f"{obj} se queda sin nadie a cargo.")
        return redirect("core:resource-detail", pk=obj.pk)

    return render(request, "core/care.html", {
        "obj": obj,
        "personas": Party.objects.filter(kind=Party.Kind.PERSON),
        "actual": responsibilities.responsible_of(obj),
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


CICLO_DE_SCHEDULE = {"yearly": "yearly", "monthly": "monthly"}
MESES_A_CICLO = {1: "monthly", 2: "bimonthly", 3: "quarterly",
                 6: "semiannual", 12: "yearly"}


def _ciclo_de(regla) -> str | None:
    """Cada cuánto cobra una regla propia, si es que se repite.

    Una regla de fecha única o atada a un vencimiento no es un recurrente: sale
    una vez y no tiene sentido sumarla a lo que te cuesta el mes.
    """
    horario = regla.schedule or {}
    for clave, ciclo in CICLO_DE_SCHEDULE.items():
        if clave in horario:
            return ciclo
    if "every" in horario:
        return MESES_A_CICLO.get(int(horario["every"].get("months", 1)))
    return None


def _reglas_propias(household) -> list:
    """Las reglas que programa el usuario, como recurrentes."""
    from .registry import Recurring
    from .schedule import next_occurrences

    hoy = dt.date.today()
    salida = []
    # Las pausadas entran igual: si desaparecieran no habria desde donde
    # reanudarlas. Quedan fuera de la suma, no de la lista.
    for regla in ObligationRule.objects.all():
        ciclo = _ciclo_de(regla)
        if not ciclo:
            continue
        proximas = next_occurrences(regla.schedule, hoy, count=1)
        salida.append(Recurring(
            title=regla.label,
            amount=regla.amount,
            cycle=ciclo,
            pk=regla.pk,
            is_active=regla.is_active,
            currency=regla.currency,
            counterparty=regla.counterparty,
            next_on=proximas[0] if proximas else None,
            url=reverse("core:rules"),
            source="core",
            note="lo programaste tú" if not regla.source_pack
                 else f"del pack {regla.source_pack}",
        ))
    return salida


ORIGENES = {
    "finance_income": "Lo que entra",
    "core": "Lo que programaste tú",
    "subscriptions": "Suscripciones",
    "property": "Servicios del inmueble",
    "leases": "Renta",
    "insurance": "Seguros",
    "loans": "Préstamos",
}


def rule_list(request):
    """Todo lo que te cobra cada tanto, venga del módulo que venga.

    Antes esta pantalla solo mostraba las reglas que el usuario programaba a
    mano, y eso la volvia enganosa: Netflix es una suscripcion y el agua es un
    servicio del inmueble, pero los dos son pagos recurrentes y no aparecian
    aqui. Seguir cada uno en su sitio esta bien -una suscripcion se cancela por
    una URL, un servicio cuelga de una casa- pero la pregunta "cuanto me cobran
    al mes" solo se contesta juntandolos.
    """
    partidas = registry.recurring_all(request.household) + \
        _reglas_propias(request.household)
    partidas.sort(key=lambda r: (not r.is_active, -(float(r.per_month or 0))))

    grupos = {}
    for partida in partidas:
        grupos.setdefault(ORIGENES.get(partida.source, "Otros"), []).append(partida)

    vivas = [r for r in partidas if r.is_active]
    entra = sum(r.per_month for r in vivas
                if r.is_income and r.per_month is not None)
    sale = sum(r.per_month for r in vivas
               if not r.is_income and r.per_month is not None)

    return render(request, "core/rules.html", {
        # Lo que entra primero: es lo que da sentido a todo lo demás.
        "grupos": sorted(grupos.items(), key=lambda kv: (
            not kv[1][0].is_income,
            -sum(float(r.per_month or 0) for r in kv[1] if r.is_active))),
        "entra": entra,
        "al_mes": sale,
        "al_ano": sale * 12,
        "queda": entra - sale,
        "cuantos": len(vivas),
        "sin_importe": [r for r in vivas if r.amount is None],
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


def transfer_new(request):
    """Mover dinero entre cuentas tuyas, que no es gastarlo."""
    from .forms import TransferForm

    form = TransferForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        entry = form.save()
        messages.success(request, f"«{entry.description}» registrado.")
        return redirect("finance:accounts")
    return render(request, "core/form.html", {
        "form": form, "title": "Registrar un traspaso", "submit": "Registrar",
        "cancel_url": "finance:accounts",
    })


def income_new(request):
    form = IncomeEntryForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        entry = form.save()
        messages.success(request, f"«{entry.description}» registrado.")
        return redirect("finance:accounts")
    return render(request, "core/form.html", {
        "form": form, "title": "Registrar un ingreso", "submit": "Registrar",
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


# --- El hogar y quién entra -------------------------------------------------


def _asegurar_titular(request):
    """Que quien instaló esto sea titular antes de invitar a nadie.

    En modo de un solo hogar no hace falta membresia para usar el sistema, asi
    que muchas instalaciones no tienen ninguna. Si desde ahi se invita a
    alguien y luego se pasa a multiusuario, el dueno se quedaria fuera de su
    propia casa. Se crea aqui, en el unico momento en que importa.
    """
    from django.utils import timezone

    from .models import Membership

    user = request.user
    membresia = Membership.objects.filter(household=request.household,
                                          user=user).first()
    if membresia is None:
        membresia = Membership.objects.create(
            household=request.household, user=user,
            role=Membership.Role.OWNER, accepted_at=timezone.now())
    return membresia


def household_members(request):
    """Quién entra a este hogar, con qué permiso y hasta cuándo."""
    from django.conf import settings

    from .models import Membership

    yo = request.membership
    if yo is None and settings.TENANCY_MODE == "single":
        # Un solo hogar significa "esto es mío": quien entra lo administra.
        yo = Membership.objects.filter(household=request.household,
                                       user=request.user).first()

    miembros = list(
        Membership.objects.filter(household=request.household)
        .select_related("user").order_by("role", "user__display_name")
    )
    from django.conf import settings

    return render(request, "core/household.html", {
        "miembros": miembros,
        "pendientes": [m for m in miembros if not m.is_accepted],
        "caducados": [m for m in miembros if m.is_expired],
        "yo": yo,
        "puedo_administrar": (yo.can_admin if yo
                              else settings.TENANCY_MODE == "single"),
    })


def household_edit(request):
    """Cambiar el nombre del hogar y dónde vive."""
    from .forms import HouseholdForm

    # Sin `_asegurar_titular`: cambiar el nombre no es invitar a nadie, y no
    # hay por qué crear una membresía como efecto secundario de abrir una
    # pantalla. Quién puede entrar aquí ya lo decide el middleware.
    form = HouseholdForm(request.POST or None, instance=request.household,
                         household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Guardado.")
        return redirect("core:household")

    return render(request, "core/form.html", {
        "form": form, "title": "Datos del hogar", "submit": "Guardar",
        "cancel_url": "core:household",
    })


def member_invite(request):
    from .forms import MemberForm

    _asegurar_titular(request)
    form = MemberForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        membresia = form.save()
        token = membresia.new_invite()
        enlace = request.build_absolute_uri(
            reverse("core:invite-accept", args=[token]))
        messages.success(
            request,
            f"Pásale este enlace a {membresia.user}: {enlace}")
        return redirect("core:household")

    return render(request, "core/form.html", {
        "form": form, "title": "Invitar a alguien", "submit": "Invitar",
        "cancel_url": "core:household",
    })


def member_edit(request, pk):
    from .forms import MemberForm
    from .models import Membership

    membresia = get_object_or_404(Membership, pk=pk,
                                  household=request.household)
    form = MemberForm(request.POST or None, instance=membresia,
                      household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{membresia.user}: cambios guardados.")
        return redirect("core:household")

    return render(request, "core/form.html", {
        "form": form, "title": str(membresia.user), "submit": "Guardar",
        "cancel_url": "core:household",
    })


def member_remove(request, pk):
    """Quitarle el acceso a alguien. No borra nada de lo que registró."""
    from .models import Membership

    membresia = get_object_or_404(Membership, pk=pk,
                                  household=request.household)
    if membresia.role == Membership.Role.OWNER:
        messages.error(request, "Al titular no se le quita el acceso.")
        return redirect("core:household")
    if request.membership and membresia.pk == request.membership.pk:
        messages.error(request, "No puedes quitarte el acceso a ti mismo.")
        return redirect("core:household")

    quien = str(membresia.user)
    membresia.delete()
    messages.success(request, f"{quien} ya no entra. Lo que registró se queda.")
    return redirect("core:household")


@login_not_required
def invite_accept(request, token):
    """Entrar por primera vez con el enlace de invitación.

    El token es de un solo uso y se borra al aceptar: un enlace que sigue
    valiendo despues de usarlo acaba reenviado en un chat familiar.
    """
    from django.contrib.auth import login
    from django.utils import timezone

    from .forms import AcceptInviteForm
    from .models import Membership

    membresia = Membership.objects.filter(invite_token=token).first() \
        if token else None
    if membresia is None:
        raise Http404("Esa invitación no existe o ya se usó.")
    if membresia.is_expired:
        raise Http404("Esa invitación caducó.")

    form = AcceptInviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = membresia.user
        usuario.set_password(form.cleaned_data["password1"])
        usuario.save(update_fields=["password"])
        membresia.accepted_at = timezone.now()
        membresia.invite_token = ""
        membresia.save(update_fields=["accepted_at", "invite_token",
                                      "updated_at"])
        login(request, usuario,
              backend="django.contrib.auth.backends.ModelBackend")
        request.session["household_id"] = str(membresia.household_id)
        messages.success(request, f"Bienvenido a {membresia.household}.")
        return redirect("core:dashboard")

    return render(request, "core/invite.html", {
        "form": form, "membresia": membresia,
    })


def household_switch(request, pk):
    """Cambiar de hogar, validando siempre contra las membresías."""
    from .models import Membership

    membresia = Membership.objects.filter(
        user=request.user, household_id=pk, accepted_at__isnull=False
    ).first()
    if membresia is None or not membresia.is_live:
        raise Http404("No entras a ese hogar.")
    request.session["household_id"] = str(pk)
    return redirect("core:dashboard")
