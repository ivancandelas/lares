import datetime as dt

from lares.core.registry import Check, Finding

from .models import Task


class OverdueTasks(Check):
    key = "tasks.overdue"
    label = "Tareas vencidas"
    severity = "normal"

    def run(self, household):
        vencidas = Task.objects.filter(status=Task.Status.OPEN, due_on__lt=dt.date.today())
        if not vencidas:
            return []
        n = len(vencidas)
        return [Finding(
            check=self.key,
            title="Una tarea pasada de fecha" if n == 1 else f"{n} tareas pasadas de fecha",
            detail=", ".join(t.title for t in vencidas[:5]),
            severity=self.severity,
        )]
