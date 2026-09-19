from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ContributionForm, GoalForm
from .models import Goal


def goal_list(request):
    metas = list(Goal.objects.filter(is_active=True))
    return render(request, "goals/list.html", {
        "juntar": [m for m in metas if not m.is_payoff],
        "saldar": [m for m in metas if m.is_payoff],
        "cumplidas": [m for m in metas if m.is_reached],
        "al_mes": sum(m.monthly_needed or 0 for m in metas if not m.is_reached),
        "cerradas": Goal.objects.filter(is_active=False)[:10],
    })


def goal_detail(request, pk):
    meta = get_object_or_404(Goal, pk=pk)
    return render(request, "goals/detail.html", {
        "meta": meta,
        "aportaciones": meta.contributions.all()[:24],
    })


def contribute(request, pk):
    meta = get_object_or_404(Goal, pk=pk)
    form = ContributionForm(request.POST or None, goal=meta,
                            household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Apartado para {meta.name}.")
        return redirect("goals:detail", pk=meta.pk)

    return render(request, "core/form.html", {
        "form": form, "title": f"Apartar para {meta.name}",
        "submit": "Apartar", "cancel_url": "goals:detail", "cancel_arg": meta.pk,
    })


def close(request, pk):
    """Cerrar una meta: cumplida, abandonada o ya no importa."""
    meta = get_object_or_404(Goal, pk=pk)
    meta.is_active = False
    meta.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"«{meta.name}» cerrada.")
    return redirect("goals:list")


def goal_new(request):
    form = GoalForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        meta = form.save()
        messages.success(request, f"«{meta.name}» abierta.")
        return redirect("goals:detail", pk=meta.pk)

    return render(request, "core/form.html", {
        "form": form, "title": "Nueva meta", "submit": "Abrir la meta",
        "cancel_url": "goals:list",
    })


def goal_edit(request, pk):
    meta = get_object_or_404(Goal, pk=pk)
    form = GoalForm(request.POST or None, instance=meta,
                    household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("goals:detail", pk=meta.pk)

    return render(request, "core/form.html", {
        "form": form, "title": meta.name, "submit": "Guardar cambios",
        "cancel_url": "goals:detail", "cancel_arg": meta.pk,
    })
