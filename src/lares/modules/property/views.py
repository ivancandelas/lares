from django.shortcuts import render

from .models import Property, Service


def property_list(request):
    activos = Property.objects.filter(status=Property.Status.ACTIVE)
    mios = [p for p in activos if p.is_mine]
    return render(request, "property/list.html", {
        "mios": mios,
        "ajenos": [p for p in activos if not p.is_mine],
        "valor_mio": sum(p.current_value or p.purchase_amount or 0 for p in mios),
        "servicios": Service.objects.filter(status=Service.Status.ACTIVE),
    })
