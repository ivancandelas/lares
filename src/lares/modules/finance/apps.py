from lares.core.registry import (
    DashboardWidget,
    DetailTab,
    LaresModule,
    LinkRole,
    NavItem,
    Registry,
)


class FinanceModule(LaresModule):
    name = "lares.modules.finance"
    label = "finance"
    label_verbose = "Dinero"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "wallet"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, services, widgets
        from .forms import CreditCardForm
        from .models import CreditCard

        reg.resource(CreditCard, kind="credit_card", form=CreditCardForm)

        reg.link_role(LinkRole(
            key="paid_from", label="Se paga desde",
            inverse_key="pays_for", inverse_label="Paga",
            to_kinds=("credit_card",),
        ))

        reg.calculation("net_worth", services.net_worth)
        reg.obligations(obligations.CardPaymentProvider)
        reg.check(checks.CardWithoutStatement, checks.CardOverLimit,
                  checks.CannotPayInFull, checks.BudgetPace)
        reg.demo_seeder(demo.seed)
        reg.nav(
            NavItem("Cuentas y tarjetas", "finance:accounts", icon="wallet",
                    order=10, section="money"),
            NavItem("Entra y sale", "finance:spending", icon="pie",
                    order=15, section="money"),
            NavItem("Cómo estás", "finance:health", icon="heart",
                    order=13, section="money"),
            NavItem("Topes de gasto", "finance:budgets", icon="gauge",
                    order=14, section="money"),
            NavItem("Dinero apartado", "finance:provisions", icon="lock",
                    order=16, section="money"),
            NavItem("¿Me alcanza?", "finance:cash-flow", icon="trend",
                    order=17, section="money"),
        )
        reg.tabs(DetailTab(
            key="finance.cost",
            label="Lo que te cuesta tenerlo",
            template="finance/_cost.html",
            provider=lambda recurso: services.cost_of(recurso),
            order=10,
        ))
        reg.widget(DashboardWidget(
            key="finance.cards",
            label="Tarjetas",
            template="finance/widget_cards.html",
            provider=widgets.cards,
            order=40,
        ))
