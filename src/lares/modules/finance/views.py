from django.shortcuts import get_object_or_404, render

from lares.core.models import Account, Entry, Party
from lares.core.services import spending

from .models import CreditCard

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
    })


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
