from django.shortcuts import render

from .models import Subscription


def subscription_list(request):
    """Lo que tienes contratado, con la cifra que nadie tiene a mano: el año."""
    activas = list(Subscription.objects.filter(status=Subscription.Status.ACTIVE))
    mias = [s for s in activas if s.is_mine_to_cancel]
    ajenas = [s for s in activas if not s.is_mine_to_cancel]

    por_tipo = {}
    for s in activas:
        por_tipo.setdefault(s.get_service_kind_display(), []).append(s)

    return render(request, "subscriptions/list.html", {
        "mias": mias,
        "ajenas": ajenas,
        "por_tipo": sorted(por_tipo.items(),
                           key=lambda kv: -sum(s.yearly_cost or 0 for s in kv[1])),
        "anual": sum(s.yearly_cost or 0 for s in activas),
        "mensual": sum(s.monthly_cost or 0 for s in activas),
        "anual_ajenas": sum(s.yearly_cost or 0 for s in ajenas),
        "canceladas": Subscription.objects.filter(
            status=Subscription.Status.DISPOSED)[:10],
    })
