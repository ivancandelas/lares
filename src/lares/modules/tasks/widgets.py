from .models import Task


def open_tasks(household):
    return {"tasks": Task.objects.filter(status=Task.Status.OPEN)[:8]}
