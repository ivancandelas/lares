"""Modulo de referencia: vehiculos.

Existe para demostrar que los puntos de extension del nucleo alcanzan para un
dominio completo sin tocar una linea del core. Si algun dia un modulo necesita
modificar el nucleo para funcionar, el nucleo esta mal.
"""

from lares.core.registry import DashboardWidget, LaresModule, LinkRole, NavItem, Registry


class VehiclesModule(LaresModule):
    name = "lares.modules.vehicles"
    label = "vehicles"
    label_verbose = "Vehiculos"
    version = "0.1.0"
    depends = ("lares.core",)
    icon = "car"
    tier = "standard"

    def register(self, reg: Registry) -> None:
        from . import checks, obligations, widgets
        from .models import Vehicle

        reg.resource(Vehicle, kind="vehicle")

        reg.link_role(LinkRole(
            key="maintained_by", label="Mantenido por",
            inverse_key="maintains", inverse_label="Da servicio a",
            from_kinds=("vehicle",),
        ))

        reg.obligations(
            obligations.VerificacionProvider,
            obligations.RefrendoProvider,
            obligations.ServiceIntervalProvider,
        )

        reg.check(
            checks.VehicleWithoutPolicy,
            checks.VehicleWithoutInvoice,
        )

        reg.nav(NavItem(label="Vehiculos", url_name="vehicles:list", icon="car", order=30))

        reg.widget(DashboardWidget(
            key="vehicles.upcoming",
            label="Vehiculos",
            template="vehicles/widget_upcoming.html",
            provider=widgets.upcoming,
            order=30,
        ))

    def connect_signals(self) -> None:
        from . import receivers  # noqa: F401
