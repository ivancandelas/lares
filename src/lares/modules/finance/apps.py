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
        from .models import CreditCard

        reg.resource(CreditCard, kind="credit_card")

        reg.link_role(LinkRole(
            key="paid_from", label="Se paga desde",
            inverse_key="pays_for", inverse_label="Paga",
            to_kinds=("credit_card",),
        ))

        reg.obligations(obligations.CardPaymentProvider)
        reg.check(checks.CardWithoutStatement, checks.CardOverLimit)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem(label="Dinero", url_name="finance:accounts", icon="wallet", order=40))
        reg.widget(DashboardWidget(
            key="finance.cards",
            label="Tarjetas",
            template="finance/widget_cards.html",
            provider=widgets.cards,
            order=40,
        ))
