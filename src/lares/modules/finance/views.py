import datetime as dt

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from lares.core.models import Account, Entry, Party
from lares.core.services import spending

from . import services
from .forms import InstallmentPlanForm, ProvisionForm
from .models import CreditCard
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


def card_detail(request, pk):
    """El estado real de una tarjeta: lo que debes y lo que te toca pagar."""
    tarjeta = get_object_or_404(CreditCard, pk=pk)
    planes = [p for p in tarjeta.installment_plans.filter(is_active=True)]
    return render(request, "finance/card.html", {
        "card": tarjeta,
        "planes": sorted(planes, key=lambda p: p.is_finished),
        "corte": tarjeta.last_cut(),
        "vence": tarjeta.next_due(),
    })


def installment_new(request):
    form = InstallmentPlanForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        plan = form.save()
        messages.success(
            request,
            f"Registrado: {plan.installment:,.0f} al mes durante {plan.months} meses.",
        )
        return redirect("finance:card", pk=plan.card_id)

    return render(request, "core/form.html", {
        "form": form, "title": "Registrar una compra a meses",
        "submit": "Registrar", "cancel_url": "finance:accounts",
    })


def budgets(request):
    """El ritmo del mes. Vive dentro del presupuesto, no aparte.

    Se conserva la direccion porque era una pantalla propia: llegar a un 404
    tras haberla usado meses es peor que un salto.
    """
    return redirect("finance:plans")



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


# --- Presupuesto: previsto contra real --------------------------------------


def plans(request):
    """Los presupuestos abiertos, con su desviación proyectada."""
    from .models_plan import Plan
    from .services_plan import report as plan_report

    abiertos = list(Plan.objects.filter(is_active=True))
    return render(request, "finance/plans.html", {
        "informes": [plan_report(request.household, p) for p in abiertos],
        "cerrados": Plan.objects.filter(is_active=False)[:10],
    })


def plan_detail(request, pk):
    from .models_plan import Plan
    from .services_plan import report as plan_report

    plan = get_object_or_404(Plan, pk=pk)
    return render(request, "finance/plan.html", {
        "plan": plan,
        "informe": plan_report(request.household, plan),
    })


def plan_new(request):
    from .forms import PlanForm

    form = PlanForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        plan = form.save()
        messages.success(request, f"«{plan.name}» creado. Ahora las categorías.")
        return redirect("finance:plan", pk=plan.pk)
    return render(request, "core/form.html", {
        "form": form, "title": "Nuevo presupuesto", "submit": "Crear",
        "cancel_url": "finance:plans",
    })


def plan_edit(request, pk):
    from .forms import PlanForm
    from .models_plan import Plan

    plan = get_object_or_404(Plan, pk=pk)
    form = PlanForm(request.POST or None, instance=plan,
                    household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("finance:plan", pk=plan.pk)
    return render(request, "core/form.html", {
        "form": form, "title": plan.name, "submit": "Guardar cambios",
        "cancel_url": "finance:plan", "cancel_arg": plan.pk,
    })


def plan_line_new(request, pk):
    from .forms import PlanLineForm
    from .models_plan import Plan

    plan = get_object_or_404(Plan, pk=pk)
    form = PlanLineForm(request.POST or None, plan=plan,
                        household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoría añadida.")
        return redirect("finance:plan", pk=plan.pk)
    return render(request, "core/form.html", {
        "form": form, "title": f"Categoría de {plan.name}", "submit": "Añadir",
        "cancel_url": "finance:plan", "cancel_arg": plan.pk,
    })


def plan_line_edit(request, pk):
    from .forms import PlanLineForm
    from .models_plan import PlanLine

    linea = get_object_or_404(PlanLine, pk=pk)
    form = PlanLineForm(request.POST or None, instance=linea, plan=linea.plan,
                        household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("finance:plan", pk=linea.plan_id)
    return render(request, "core/form.html", {
        "form": form, "title": str(linea.account), "submit": "Guardar cambios",
        "cancel_url": "finance:plan", "cancel_arg": linea.plan_id,
    })


def plan_seed(request, pk):
    """Partir de lo que de verdad se gastó el año pasado."""
    from .models_plan import Plan
    from .services_plan import seed_from

    plan = get_object_or_404(Plan, pk=pk)
    ano = int(request.GET.get("de") or ((plan.year or dt.date.today().year) - 1))
    creadas = seed_from(request.household, plan, ano)
    if creadas:
        messages.success(request, f"{creadas} categorías traídas de {ano}. "
                                  f"Ajusta lo que vaya a cambiar.")
    else:
        messages.info(request, f"No hay gasto registrado en {ano} que traer.")
    return redirect("finance:plan", pk=plan.pk)


# --- Ingresos recurrentes ---------------------------------------------------


def income_new(request):
    from .forms import RecurringIncomeForm

    form = RecurringIncomeForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        ingreso = form.save()
        messages.success(request, f"«{ingreso.name}» registrado.")
        return redirect("core:rules")
    return render(request, "core/form.html", {
        "form": form, "title": "Nuevo ingreso recurrente", "submit": "Guardar",
        "cancel_url": "core:rules",
    })


def income_edit(request, pk):
    from .forms import RecurringIncomeForm
    from .models_income import RecurringIncome

    ingreso = get_object_or_404(RecurringIncome, pk=pk)
    form = RecurringIncomeForm(request.POST or None, instance=ingreso,
                               household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("core:rules")
    return render(request, "core/form.html", {
        "form": form, "title": ingreso.name, "submit": "Guardar cambios",
        "cancel_url": "core:rules",
    })
