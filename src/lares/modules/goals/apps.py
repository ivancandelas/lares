from lares.core.registry import DashboardWidget, LaresModule, NavItem, Registry


class GoalsModule(LaresModule):
    name = "lares.modules.goals"
    label = "goals"
    label_verbose = "Metas"
    version = "0.1.0"
    # Depende de dinero porque una meta se apoya en una provision para apartar
    # de verdad, y en una cuenta para medir una deuda por su saldo.
    depends = ("lares.core", "lares.modules.finance")
    icon = "target"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, widgets

        reg.check(checks.Behind, checks.NoPace, checks.Stalled,
                  checks.Reached, checks.DebtGrowing)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem("Metas", "goals:list", icon="target",
                        order=18, section="money"))
        reg.widget(DashboardWidget(
            key="goals.progress",
            label="Metas",
            template="goals/widget_goals.html",
            provider=widgets.goals,
            order=55,
        ))
