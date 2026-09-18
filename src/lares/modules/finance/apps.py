from lares.core.registry import DashboardWidget, LaresModule, LinkRole, NavItem, Registry


class FinanceModule(LaresModule):
    name = "lares.modules.finance"
    label = "finance"
    label_verbose = "Dinero"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "wallet"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, widgets
        from .forms import CreditCardForm
        from .models import CreditCard

        reg.resource(CreditCard, kind="credit_card", form=CreditCardForm)

        reg.link_role(LinkRole(
            key="paid_from", label="Se paga desde",
            inverse_key="pays_for", inverse_label="Paga",
            to_kinds=("credit_card",),
        ))

        reg.obligations(obligations.CardPaymentProvider)
        reg.check(checks.CardWithoutStatement, checks.CardOverLimit)
        reg.demo_seeder(demo.seed)
        reg.nav(
            NavItem("Cuentas y tarjetas", "finance:accounts", icon="wallet",
                    order=10, section="money"),
            NavItem("Entra y sale", "finance:spending", icon="pie",
                    order=15, section="money"),
        )
        reg.widget(DashboardWidget(
            key="finance.cards",
            label="Tarjetas",
            template="finance/widget_cards.html",
            provider=widgets.cards,
            order=40,
        ))
