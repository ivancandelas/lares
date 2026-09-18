from lares.core.registry import DashboardWidget, LaresModule, LinkRole, NavItem, Registry


class PropertyModule(LaresModule):
    name = "lares.modules.property"
    label = "property"
    label_verbose = "Inmuebles"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "home"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, widgets
        from .forms import PropertyForm, ServiceForm
        from .models import Property, Service

        reg.resource(Property, kind="property", form=PropertyForm)
        reg.resource(Service, kind="service", form=ServiceForm)

        reg.link_role(LinkRole(
            key="serves", label="Da servicio a",
            inverse_key="served_by", inverse_label="Recibe servicio de",
            from_kinds=("service",), to_kinds=("property",),
        ))

        reg.obligations(obligations.PredialProvider, obligations.LeaseProvider,
                        obligations.ServiceBillProvider)
        reg.check(checks.PropertyWithoutDeed, checks.PropertyWithoutInsurance,
                  checks.RentedWithoutDeposit, checks.PropertyWithoutServices)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem("Inmuebles", "property:list", icon="home", order=10,
                        section="holdings"))
        reg.widget(DashboardWidget(
            key="property.portfolio",
            label="Inmuebles",
            template="property/widget_portfolio.html",
            provider=widgets.portfolio,
            order=15,
        ))
