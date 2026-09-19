from lares.core.registry import DetailTab, LaresModule, NavItem, Registry


class MaintenanceModule(LaresModule):
    name = "lares.modules.maintenance"
    label = "maintenance"
    label_verbose = "Mantenimiento"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "wrench"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, services
        from .models import MaintenancePlan

        # Los planes son sujetos de obligación aunque no sean recursos: no se
        # poseen, se cumplen.
        reg.subject_source(
            "maintenance_plan",
            lambda household: MaintenancePlan.objects.filter(is_active=True),
        )
        reg.obligations(obligations.MaintenanceProvider)
        reg.check(checks.OverdueMaintenance, checks.WorkWithoutProvider)
        from .related import for_party as maintenance_links
        reg.related(maintenance_links)
        reg.demo_seeder(demo.seed)
        # Sin `resource_kind` la pestaña sale en la ficha de cualquier cosa:
        # un coche, una casa, un refrigerador o una guitarra. A todos se les
        # hacen trabajos, y el módulo no tiene por qué saber cuáles existen.
        reg.tabs(DetailTab(
            key="maintenance.history",
            label="Historial de mantenimiento",
            template="maintenance/_history.html",
            provider=services.history_tab,
            order=20,
        ))
        reg.nav(
            NavItem("Mantenimiento", "maintenance:list", icon="wrench", order=50,
                    section="holdings"),
            NavItem("Proveedores", "maintenance:providers", icon="users", order=15,
                    section="more"),
        )
