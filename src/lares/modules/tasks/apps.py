from lares.core.registry import DashboardWidget, LaresModule, NavItem, Registry


class TasksModule(LaresModule):
    name = "lares.modules.tasks"
    label = "tasks"
    label_verbose = "Tareas"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "check"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, widgets

        reg.check(checks.OverdueTasks)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem("Tareas", "tasks:list", icon="check", order=20, section="main"))
        reg.widget(DashboardWidget(
            key="tasks.open",
            label="Tareas abiertas",
            template="tasks/widget_open.html",
            provider=widgets.open_tasks,
            order=20,
        ))
