from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from lares.core.services import obligations as obligation_service

from .forms import MaintenancePlanForm, WorkOrderForm
from .models import MaintenancePlan, WorkOrder
from .services import providers


def overview(request):
    return render(request, "maintenance/list.html", {
        "planes": MaintenancePlan.objects.filter(is_active=True),
        "trabajos": WorkOrder.objects.all()[:20],
    })


def provider_list(request):
    return render(request, "maintenance/providers.html",
                  {"proveedores": providers(request.household)})


def plan_new(request):
    return _form(request, MaintenancePlanForm, "Nuevo plan de mantenimiento")


def plan_edit(request, pk):
    return _form(request, MaintenancePlanForm, "Editar plan",
                 instance=get_object_or_404(MaintenancePlan, pk=pk))


def work_new(request):
    # `?de=` llega desde la ficha de la cosa: si ya sabemos sobre qué es, no
    # tiene sentido volver a preguntarlo.
    inicial = {}
    if sujeto := request.GET.get("de"):
        from lares.core.models import Resource

        if Resource.objects.filter(pk=sujeto).exists():
            inicial = {"subject": sujeto}
    return _form(request, WorkOrderForm, "Registrar un trabajo hecho",
                 initial=inicial)


def _form(request, form_class, title, instance=None, initial=None):
    form = form_class(request.POST or None, instance=instance,
                      initial=initial or {}, household=request.household)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        obligation_service.materialize(request.household)
        messages.success(request, f"{obj} guardado.")
        return redirect("maintenance:list")
    return render(request, "core/form.html", {
        "form": form, "title": title, "submit": "Guardar",
        "cancel_url": "maintenance:list",
    })
