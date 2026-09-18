from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from lares.core.models import Account, Entry, Party
from lares.core.services import spending

from . import services
from .forms import BudgetForm, ProvisionForm
from .models import CreditCard
from .models_budget import Budget
from .models_provision import Provision

# La partida doble es una decision interna: nadie quiere leer "Pasivo" en la
# pantalla de su casa. Los nombres contables se quedan en la base de datos.
NOMBRES = {
    Account.Type.ASSET: "Cuentas",
    Account.Type.LIABILITY: "Deudas",
    Account.Type.EXPENSE: "En qué se va",
    Account.Type.INCOME: "De dónde viene",
    Account.Type.EQUITY: "Patrimonio",
}
ORDEN = [Account.Type.ASSET, Account.Type.LIABILITY, Account.Type.INCOME, Account.Type.EXPENSE]


def accounts(request):
    cuentas = list(Account.objects.filter(is_active=True))
    disponible = services.available(request.household)
    por_tipo = {}
    for tipo in ORDEN:
        del_tipo = [c for c in cuentas if c.type == tipo]
        if del_tipo:
            por_tipo[NOMBRES[tipo]] = del_tipo

    activos = sum(c.balance for c in cuentas if c.type == Account.Type.ASSET)
    pasivos = sum(c.balance for c in cuentas if c.type == Account.Type.LIABILITY)

    return render(request, "finance/accounts.html", {
        "por_tipo": por_tipo,
        "cards": CreditCard.objects.filter(status=CreditCard.Status.ACTIVE),
        "activos": activos,
        "pasivos": pasivos,
        "neto": activos - pasivos,
        "movimientos": Entry.objects.prefetch_related("postings__account")[:12],
        "disponible": disponible,
    })


def provisions(request):
    """Lo apartado y lo que queda de verdad."""
    return render(request, "finance/provisions.html", {
        **services.available(request.household),
        "sugerencias": services.suggest_provisions(request.household),
    })


def provision_new(request):
    inicial = {}
    if clave := request.GET.get("de"):
        from lares.core.models import Obligation

        origen = Obligation.objects.filter(dedupe_key=clave).first()
        if origen:
            inicial = {"name": origen.title, "target_amount": origen.amount,
                       "due_on": origen.due_on}

    form = ProvisionForm(request.POST or None, initial=inicial,
                         household=request.household)
    if request.method == "POST" and form.is_valid():
        provision = form.save()
        if clave:
            provision.source_key = clave
            provision.save(update_fields=["source_key", "updated_at"])
        messages.success(request, f"Apartado para {provision.name}.")
        return redirect("finance:provisions")

    return render(request, "core/form.html", {
        "form": form, "title": "Apartar dinero para algo",
        "submit": "Apartar", "cancel_url": "finance:provisions",
    })


def provision_edit(request, pk):
    provision = get_object_or_404(Provision, pk=pk)
    form = ProvisionForm(request.POST or None, instance=provision,
                         household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("finance:provisions")
    return render(request, "core/form.html", {
        "form": form, "title": provision.name, "submit": "Guardar cambios",
        "cancel_url": "finance:provisions",
    })


def budgets(request):
    """Cuánto has puesto de tope y a qué ritmo vas."""
    return render(request, "finance/budgets.html",
                  services.budgets(request.household))


def budget_new(request):
    form = BudgetForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Presupuesto guardado.")
        return redirect("finance:budgets")
    return render(request, "core/form.html", {
        "form": form, "title": "Poner un tope a una categoría",
        "submit": "Guardar", "cancel_url": "finance:budgets",
    })


def budget_edit(request, pk):
    presupuesto = get_object_or_404(Budget, pk=pk)
    form = BudgetForm(request.POST or None, instance=presupuesto,
                      household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("finance:budgets")
    return render(request, "core/form.html", {
        "form": form, "title": str(presupuesto.account), "submit": "Guardar cambios",
        "cancel_url": "finance:budgets",
    })


def health(request):
    """Cuatro indicadores que dicen más que cualquier gráfica."""
    return render(request, "finance/health.html", services.health(request.household))


def cash_flow(request):
    meses = int(request.GET.get("meses") or 6)
    return render(request, "finance/cash_flow.html",
                  services.cash_flow(request.household, months=min(meses, 24)))


def where_it_goes(request):
    """En qué se va: por categoría, por comercio, por persona y por cosa."""
    return render(request, "finance/spending.html",
                  spending.report(request.household, request.GET.get("periodo", "quarter")))


def merchant(request, pk):
    party = get_object_or_404(Party, pk=pk)
    contexto = spending.merchant_detail(request.household, party,
                                        request.GET.get("periodo", "year"))
    contexto["periods"] = [(k, v[0]) for k, v in spending.PERIODOS.items()]
    contexto["period"] = request.GET.get("periodo", "year")
    return render(request, "finance/merchant.html", contexto)


# ---------------------------------------------------------------------------
# Importar un estado de cuenta
# ---------------------------------------------------------------------------


def import_statement(request):
    """Subir el archivo del banco y ver qué va a pasar antes de que pase."""
    from . import importing, statements

    cuentas = Account.objects.filter(
        type__in=[Account.Type.ASSET, Account.Type.LIABILITY], is_active=True
    )

    if request.method == "POST" and request.FILES.get("file"):
        archivo = request.FILES["file"]
        cuenta = get_object_or_404(Account, pk=request.POST.get("account"))
        contenido = archivo.read()
        movimientos, cabeceras, mapa = statements.read(contenido, archivo.name)

        if not movimientos:
            messages.success(
                request,
                "No reconocí ningún movimiento en ese archivo. "
                "Prueba con el CSV o el OFX que ofrece tu banco.",
            )
            return redirect("finance:import")

        filas = importing.reconcile(request.household, cuenta, movimientos)
        request.session["import_pending"] = {
            "account": str(cuenta.pk),
            "movements": [
                {"date": str(m.date), "description": m.description,
                 "amount": str(m.amount), "external_ref": m.external_ref}
                for m in movimientos
            ],
        }
        return render(request, "finance/import_preview.html", {
            "cuenta": cuenta,
            "filas": filas,
            "nuevos": sum(1 for f in filas if f.status == "new"),
            "encajan": sum(1 for f in filas if f.status == "match"),
            "conocidos": sum(1 for f in filas if f.status == "known"),
            "categorias": Account.objects.filter(type=Account.Type.EXPENSE),
        })

    return render(request, "finance/import.html", {"cuentas": cuentas})


def import_confirm(request):
    """Aplicar lo revisado. Nada se creó hasta este momento."""
    import datetime as _dt
    from decimal import Decimal as _D

    from . import importing, statements

    pendiente = request.session.get("import_pending")
    if request.method != "POST" or not pendiente:
        return redirect("finance:import")

    cuenta = get_object_or_404(Account, pk=pendiente["account"])
    movimientos = [
        statements.Movement(
            date=_dt.date.fromisoformat(m["date"]), description=m["description"],
            amount=_D(m["amount"]), external_ref=m["external_ref"],
        )
        for m in pendiente["movements"]
    ]
    filas = importing.reconcile(request.household, cuenta, movimientos)

    gasto = importing.default_category(request.household, _D("-1"))
    ingreso = importing.default_category(request.household, _D("1"))
    for fila in filas:
        if fila.is_new:
            fila.account_guess = gasto if fila.movement.amount < 0 else ingreso

    resultado = importing.apply(request.household, cuenta, gasto, filas)
    request.session.pop("import_pending", None)

    messages.success(
        request,
        f"{resultado['created']} movimientos nuevos, "
        f"{resultado['linked']} enlazados con lo que ya tenías y "
        f"{resultado['known']} que ya estaban.",
    )
    return redirect("finance:accounts")
