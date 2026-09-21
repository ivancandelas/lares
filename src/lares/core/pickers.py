"""De donde salen las opciones de un desplegable, y como crear la que falta.

Las dos mitades del mismo problema, y por eso viven juntas.

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

La otra mitad es buscar. Un `<select>` con la agenda entera dentro no es un
desplegable, es una lista que hay que recorrer: con doscientos contactos son
doscientas etiquetas en el HTML de cada pantalla que lo use, y tres campos de
persona en el mismo formulario las multiplican por tres. A partir de cierto
tamano el desplegable se cambia por un buscador que trae los primeros que
coinciden. Por debajo de ese tamano NO: un selector con cuatro opciones se
maneja mejor con el control nativo, que ya sabe abrirse con el teclado y
funciona sin JavaScript.
"""

from __future__ import annotations

from dataclasses import dataclass

# A partir de cuantas opciones deja de servir un desplegable nativo.
UMBRAL_BUSCADOR = 12


@dataclass(frozen=True)
class AltaRapida:
    key: str
    title: str
    form: type
    scope: str
    # Como se buscan las opciones de este tipo.
    model: type | None = None
    search_fields: tuple = ("name",)
    # Valores que se fijan segun el desplegable desde el que se abre: la
    # categoria de un gasto es una cuenta, pero no cualquiera.
    preset_field: str = ""
    preset_labels: dict | None = None


CATALOGO: dict[str, AltaRapida] = {}


def register(alta: AltaRapida) -> None:
    CATALOGO[alta.key] = alta


def get(key: str) -> AltaRapida | None:
    return CATALOGO.get(key)


def buscar(alta: AltaRapida, household, preset: str, texto: str, limite: int):
    """Los que coinciden, y cuantos hay en total.

    El total importa: es lo que permite decir "y 43 mas" en vez de callarse,
    que es la diferencia entre "no esta" y "no esta entre los diez primeros".
    """
    from django.db.models import Q

    qs = alta.model.all_objects.filter(household=household)
    if preset and alta.preset_field:
        qs = qs.filter(**{alta.preset_field: preset})
    if hasattr(alta.model, "archived_at"):
        qs = qs.filter(archived_at__isnull=True)
    if texto:
        condicion = Q()
        for campo in alta.search_fields:
            condicion |= Q(**{f"{campo}__icontains": texto})
        qs = qs.filter(condicion)
    total = qs.count()
    return list(qs[:limite]), total


def parse(valor: str) -> tuple[str, str]:
    """«account:expense» -> («account», «expense»)."""
    clave, _, preset = (valor or "").partition(":")
    return clave, preset


def poblar() -> None:
    """Se llama al arrancar la app, cuando los formularios ya se pueden importar."""
    from .forms import QuickAccountForm, QuickLocationForm, QuickPartyForm
    from .models import Account, Location, Party

    register(AltaRapida(
        key="party", title="Nueva persona u organización",
        form=QuickPartyForm, scope="people",
        model=Party, search_fields=("name", "legal_name", "tax_id"),
        preset_field="kind",
        preset_labels={"person": "Nueva persona",
                       "organization": "Nueva organización"},
    ))
    register(AltaRapida(
        key="account", title="Nueva cuenta",
        form=QuickAccountForm, scope="finance",
        model=Account, search_fields=("name",),
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
        model=Location, search_fields=("name", "code"),
    ))
