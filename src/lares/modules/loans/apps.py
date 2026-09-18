from lares.core.registry import DashboardWidget, LaresModule, NavItem, Registry


class LoansModule(LaresModule):
    name = "lares.modules.loans"
    label = "loans"
    label_verbose = "Préstamos"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "handshake"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, widgets
        from .forms import LoanForm
        from .models import Loan
        from .related import for_party

        reg.resource(Loan, kind="loan", form=LoanForm)
        reg.obligations(obligations.PaymentProvider)
        reg.check(checks.ForgottenLoan, checks.InformalWithoutRecord, checks.Overpaid)
        reg.related(for_party)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem("Préstamos", "loans:list", icon="handshake", order=19,
                        section="money"))
        reg.widget(DashboardWidget(
            key="loans.balance",
            label="Préstamos",
            template="loans/widget_balance.html",
            provider=widgets.balance,
            order=19,
        ))
