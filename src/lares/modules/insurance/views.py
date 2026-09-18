import datetime as dt

from django.shortcuts import render

from .models import Policy


def policy_list(request):
    hoy = dt.date.today()
    activas = Policy.objects.filter(status=Policy.Status.ACTIVE)
    return render(request, "insurance/list.html", {
        "vigentes": [p for p in activas if not p.ends_on or p.ends_on >= hoy],
        "vencidas": [p for p in activas if p.ends_on and p.ends_on < hoy],
    })
