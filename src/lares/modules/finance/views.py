from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from lares.core.models import Account, Entry, Party
from lares.core.services import spending

from . import services
from .forms import ProvisionForm
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
