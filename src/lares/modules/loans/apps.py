from lares.core.registry import (
    DashboardWidget,
    DetailTab,
    LaresModule,
    LinkRole,
    NavItem,
    Registry,
)


class LoansModule(LaresModule):
    name = "lares.modules.loans"
    label = "loans"
    label_verbose = "Préstamos"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "handshake"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, owed, widgets
        from .forms import LoanForm
        from .models import Loan
        from .related import for_party

        reg.resource(Loan, kind="loan", form=LoanForm)
        reg.link_role(LinkRole(
            key="secures", label="Está garantizado por",
            inverse_key="secured_by", inverse_label="Garantiza",
            from_kinds=("loan",),
        ))
        reg.tabs(DetailTab(
            key="loans.against",
            label="Lo que debes por esto",
            template="loans/_against.html",
            provider=_deuda_de,
            order=20,
        ))
        reg.obligations(obligations.PaymentProvider)
        reg.check(checks.ForgottenLoan, checks.InformalWithoutRecord, checks.Overpaid)
        reg.related(for_party)
        reg.owed(owed.owed)
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


def _deuda_de(recurso) -> dict:
    from decimal import Decimal

    from .forms import loans_against

    prestamos = loans_against(recurso)
    deuda = sum((x.outstanding for x in prestamos), Decimal(0))
    valor = recurso.current_value or recurso.purchase_amount or Decimal(0)
    return {
        "loans": prestamos,
        "total": deuda,
        "valor": valor,
        # Lo que de verdad es tuyo de esta cosa.
        "equity": valor - deuda,
    }
