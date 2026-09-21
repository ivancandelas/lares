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
        from . import checks, demo, obligations, owed, recurring, services, widgets
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
                  checks.CannotPayInFull, checks.BudgetPace,
                  checks.InstallmentsCommitted, checks.InstallmentInterest,
                  checks.PlanDrifting, checks.PlanUnplanned,
                  checks.NegativeCash)
        reg.owed(owed.owed)
        reg.recurring(recurring.recurring)
        reg.demo_seeder(demo.seed)
        reg.nav(
            NavItem("Cuentas y tarjetas", "finance:accounts", icon="wallet",
                    order=10, section="money"),
            # La pantalla existía desde F4 y no se enlazaba desde ninguna
            # parte: solo se llegaba tecleando la dirección.
            NavItem("Importar movimientos", "finance:import", icon="upload",
                    order=15, section="money"),
            NavItem("Ingresos y gastos", "finance:spending", icon="pie",
                    order=15, section="money"),
            NavItem("Resumen mensual", "finance:statement", icon="scale",
                    order=11, section="money"),
            NavItem("Situación financiera", "finance:health", icon="heart",
                    order=13, section="money"),
            NavItem("Presupuesto", "finance:plans", icon="target",
                    order=12, section="money"),
            NavItem("Fondos apartados", "finance:provisions", icon="lock",
                    order=16, section="money"),
            NavItem("Proyección", "finance:cash-flow", icon="trend",
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
