from lares.core.registry import DashboardWidget, LaresModule, LinkRole, NavItem, Registry


class InsuranceModule(LaresModule):
    name = "lares.modules.insurance"
    label = "insurance"
    label_verbose = "Seguros"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "shield"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, widgets
        from .forms import PolicyForm
        from .models import Policy

        reg.resource(Policy, kind="policy", form=PolicyForm)

        # La arista que resuelve los "sin póliza" que avisan los demás módulos.
        reg.link_role(LinkRole(
            key="insures", label="Asegura",
            inverse_key="insured_by", inverse_label="Asegurado por",
            from_kinds=("policy",),
        ))

        reg.obligations(obligations.RenewalProvider, obligations.PremiumProvider)
        reg.check(checks.ExpiredPolicy, checks.PolicyCoversNothing,
                  checks.Underinsured)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem(label="Seguros", url_name="insurance:list", icon="shield",
                        order=35))
        reg.widget(DashboardWidget(
            key="insurance.coverage",
            label="Pólizas vigentes",
            template="insurance/widget_coverage.html",
            provider=widgets.coverage,
            order=35,
        ))
