from django.shortcuts import render

from .models import Belonging


def belonging_list(request):
    activos = Belonging.objects.filter(status=Belonging.Status.ACTIVE)
    return render(request, "belongings/list.html", {
        "valiosos": [b for b in activos if b.is_valuable],
        "resto": [b for b in activos if not b.is_valuable],
        "idos": Belonging.objects.filter(status=Belonging.Status.DISPOSED),
    })
