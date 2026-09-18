from django.shortcuts import render

from .models import Vehicle


def vehicle_list(request):
    return render(request, "vehicles/list.html", {"vehicles": Vehicle.objects.all()})
