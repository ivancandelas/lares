from lares.core.registry import DashboardWidget, LaresModule, NavItem, Registry


class TaxesModule(LaresModule):
    name = "lares.modules.taxes"
    label = "taxes"
    label_verbose = "Impuestos"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "receipt"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, widgets
        from .models import TaxProfile

        # El calendario fiscal cuelga de quien declara, no de una cosa: por eso
        # el perfil es el sujeto y no hay ningun Resource de por medio.
        reg.subject_source("tax_profile", _perfiles)
        reg.obligations(obligations.MonthlyProvisional, obligations.AnnualReturn)
        reg.check(checks.DeductibleUnmarked, checks.OverCap, checks.MissingUma,
                  checks.FilingWithoutReceipt, checks.UnfiledPeriod)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem("Impuestos", "taxes:overview", icon="receipt",
                        order=21, section="money"))
        reg.widget(DashboardWidget(
            key="taxes.next",
            label="Impuestos",
            template="taxes/widget_taxes.html",
            provider=widgets.taxes,
            order=60,
        ))
        self.profile_model = TaxProfile


def _perfiles(household):
    from .models import TaxProfile

    return list(TaxProfile.objects.filter(is_active=True)
                .select_related("taxpayer"))
