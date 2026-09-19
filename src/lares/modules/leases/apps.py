from lares.core.registry import DashboardWidget, DetailTab, LaresModule, NavItem, Registry


class LeasesModule(LaresModule):
    name = "lares.modules.leases"
    label = "leases"
    label_verbose = "Arrendamiento"
    version = "0.1.0"
    depends = ("lares.core", "lares.modules.property")
    icon = "key"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, owed, recurring, widgets
        from .forms import LeaseForm
        from .models import Lease
        from .related import for_party

        reg.resource(Lease, kind="lease", form=LeaseForm)
        reg.obligations(obligations.RentProvider, obligations.LeaseEndProvider,
                        obligations.IncreaseProvider)
        reg.check(checks.LateRent, checks.RentedWithoutLease,
                  checks.LeaseWithoutDocument, checks.DepositPending,
                  checks.NoDeposit, checks.NoInventory)
        reg.related(for_party)
        reg.owed(owed.owed)
        reg.recurring(recurring.recurring)
        reg.demo_seeder(demo.seed)
        reg.tabs(DetailTab(
            key="leases.of_property",
            label="Arrendamiento",
            template="leases/_of_property.html",
            resource_kind="property",
            provider=_contratos_de,
            order=15,
        ))
        reg.nav(
            NavItem("Arrendamiento", "leases:list", icon="key", order=45,
                    section="holdings"),
            NavItem("Rendimiento", "leases:yields", icon="trend", order=46,
                    section="holdings"),
        )
        reg.widget(DashboardWidget(
            key="leases.rent",
            label="Rentas",
            template="leases/widget_rent.html",
            provider=widgets.rent,
            order=45,
        ))


def _contratos_de(recurso) -> dict:
    from .models import Lease
    from .services import ensure_periods

    contratos = list(Lease.objects.filter(property_ref_id=recurso.pk,
                                          status=Lease.Status.ACTIVE))
    for lease in contratos:
        ensure_periods(lease)
    return {
        "leases": contratos,
        "atrasados": [p for x in contratos for p in x.overdue_payments],
    }
