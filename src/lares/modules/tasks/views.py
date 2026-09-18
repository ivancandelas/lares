import datetime as dt

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Task


def task_list(request):
    if request.method == "POST" and request.POST.get("title"):
        Task.objects.create(
            household=request.household,
            title=request.POST["title"][:250],
            due_on=_parse_date(request.POST.get("due_on")),
            priority=request.POST.get("priority") or Task.Priority.NORMAL,
        )
        return redirect("tasks:list")

    abiertas = Task.objects.filter(status=Task.Status.OPEN)
    hoy = dt.date.today()
    return render(request, "tasks/list.html", {
        "vencidas": [t for t in abiertas if t.due_on and t.due_on < hoy],
        "pendientes": [t for t in abiertas if not t.due_on or t.due_on >= hoy],
        "hechas": Task.objects.filter(status=Task.Status.DONE)[:10],
        "priorities": Task.Priority.choices,
    })


def complete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    task.status = Task.Status.DONE
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    return redirect("tasks:list")


def _parse_date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None
