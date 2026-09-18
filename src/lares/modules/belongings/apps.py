from lares.core.registry import DashboardWidget, LaresModule, NavItem, Registry


class BelongingsModule(LaresModule):
    name = "lares.modules.belongings"
    label = "belongings"
    label_verbose = "Objetos"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "box"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, widgets
        from .forms import BelongingForm
        from .models import Belonging

        reg.resource(Belonging, kind="belonging", form=BelongingForm)
        reg.obligations(obligations.WarrantyExpiryProvider)
        reg.check(checks.ValuableWithoutInvoice, checks.WarrantyWithoutProof,
                  checks.StaleValuable)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem(label="Objetos", url_name="belongings:list", icon="box", order=25))
        reg.widget(DashboardWidget(
            key="belongings.warranties",
            label="Garantías por vencer",
            template="belongings/widget_warranties.html",
            provider=widgets.warranties,
            order=25,
        ))
