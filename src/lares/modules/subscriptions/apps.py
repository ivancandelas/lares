from lares.core.registry import DashboardWidget, LaresModule, NavItem, Registry


class SubscriptionsModule(LaresModule):
    name = "lares.modules.subscriptions"
    label = "subscriptions"
    label_verbose = "Contratado"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "repeat"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, demo, obligations, recurring, widgets
        from .forms import SubscriptionForm
        from .models import Subscription
        from .related import for_party

        reg.resource(Subscription, kind="subscription", form=SubscriptionForm)
        reg.obligations(obligations.ChargeProvider, obligations.CommitmentProvider)
        reg.check(checks.WithoutPaymentMethod, checks.PriceRose,
                  checks.WorthReviewing)
        reg.related(for_party)
        reg.recurring(recurring.recurring)
        reg.demo_seeder(demo.seed)
        reg.nav(NavItem("Suscripciones", "subscriptions:list",
                        icon="repeat", order=18, section="money"))
        reg.widget(DashboardWidget(
            key="subscriptions.cost",
            label="Lo que tienes contratado",
            template="subscriptions/widget_cost.html",
            provider=widgets.cost,
            order=18,
        ))
