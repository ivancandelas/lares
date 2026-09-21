"""Dar de alta lo que falta sin perder el formulario que estabas llenando.

El caso que lo motiva pasa en todas las pantallas de alta: estas registrando
un seguro, llegas a "aseguradora" y GNP no esta dada de alta. Hoy hay que
salir, crearla y volver, y al volver los diez campos anteriores estan en
blanco. La consecuencia real no es la molestia: es que la proxima vez no
registras el seguro.

Aqui vive el catalogo de lo que se puede crear al vuelo. Cada entrada dice
que formulario minimo se ensena y que ambito hace falta para usarlo: crear una
cuenta es una accion de dinero aunque se haga desde un desplegable, y quien
tiene el dinero restringido no puede colarse por aqui.

Un formulario de alta rapida pregunta lo IMPRESCINDIBLE. Lo demas se completa
luego en su propia pantalla; si pidiera todo, seria la pantalla de la que
estamos intentando no salir.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AltaRapida:
    key: str
    title: str
    form: type
    scope: str
    # Valores que se fijan segun el desplegable desde el que se abre: la
    # categoria de un gasto es una cuenta, pero no cualquiera.
    preset_field: str = ""
    preset_labels: dict | None = None


CATALOGO: dict[str, AltaRapida] = {}


def register(alta: AltaRapida) -> None:
    CATALOGO[alta.key] = alta


def get(key: str) -> AltaRapida | None:
    return CATALOGO.get(key)


def parse(valor: str) -> tuple[str, str]:
    """«account:expense» -> («account», «expense»)."""
    clave, _, preset = (valor or "").partition(":")
    return clave, preset


def poblar() -> None:
    """Se llama al arrancar la app, cuando los formularios ya se pueden importar."""
    from .forms import QuickAccountForm, QuickLocationForm, QuickPartyForm
    from .models import Account

    register(AltaRapida(
        key="party", title="Nueva persona u organización",
        form=QuickPartyForm, scope="people",
        preset_field="kind",
        preset_labels={"person": "Nueva persona",
                       "organization": "Nueva organización"},
    ))
    register(AltaRapida(
        key="account", title="Nueva cuenta",
        form=QuickAccountForm, scope="finance",
        preset_field="type",
        preset_labels={
            Account.Type.ASSET: "Nueva cuenta",
            Account.Type.LIABILITY: "Nueva deuda",
            Account.Type.EXPENSE: "Nueva categoría de gasto",
            Account.Type.INCOME: "Nueva categoría de ingreso",
        },
    ))
    register(AltaRapida(
        key="location", title="Nueva ubicación",
        form=QuickLocationForm, scope="core",
    ))
