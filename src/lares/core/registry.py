"""Sistema de modulos de Lares.

Un modulo (addon) es una app de Django que declara `LaresModule` como AppConfig.
El nucleo no conoce autos, polizas ni escuelas: solo conoce las siete primitivas
del dominio y los puntos de extension de este archivo.

Regla de oro: un modulo NUNCA importa modelos de otro modulo. Depende del nucleo
y escucha eventos. Si necesita datos de otro, falta una primitiva en el nucleo.

Ver docs/03-module-system.md y docs/08-module-authoring.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Contratos de los puntos de extension
# ---------------------------------------------------------------------------


class ObligationProvider:
    """Genera obligaciones para una entidad.

    Debe ser una funcion pura: mismas entradas -> mismas salidas. El nucleo se
    encarga de materializar, deduplicar (por `dedupe_key`) y notificar, para que
    el proveedor pueda re-ejecutarse cuantas veces haga falta sin duplicar nada.
    """

    key: str = ""
    label: str = ""
    applies_to: str = ""          # clave de tipo de recurso, p.ej. "vehicle"

    def generate(self, subject, on_date):  # -> list[ObligationSpec]
        raise NotImplementedError


@dataclass(frozen=True)
class ObligationSpec:
    dedupe_key: str
    title: str
    due_on: object
    severity: str = "normal"      # low | normal | high | critical
    amount: object | None = None
    currency: str | None = None
    # A quien se le paga o con quien se hace el tramite. "¿A quien?" es parte
    # del aviso: sin eso, el usuario tiene que ir a buscarlo.
    counterparty: object | None = None
    remind_offsets: tuple[int, ...] = (-30, -15, -7, -1)
    payload: dict = field(default_factory=dict)


class Check:
    """Detector de huecos: 'tienes un auto sin poliza asociada'.

    Corre de forma programada y devuelve hallazgos. Es lo que convierte el
    sistema en algo que te avisa de lo que NO registraste, que es mas valioso
    que recordarte lo que si.
    """

    key: str = ""
    label: str = ""
    severity: str = "normal"

    def run(self, household):  # -> list[Finding]
        raise NotImplementedError


@dataclass(frozen=True)
class Finding:
    check: str
    title: str
    detail: str = ""
    severity: str = "normal"
    subject_type: str | None = None
    subject_id: object | None = None
    action_url: str | None = None


class Classifier:
    """Reconoce que es un archivo que acaba de entrar."""

    key: str = ""
    label: str = ""

    def classify(self, item):  # -> Proposal | None
        raise NotImplementedError


@dataclass(frozen=True)
class Proposal:
    label: str
    plan: dict
    confidence: float = 0.5


# Grupos del menú, en el orden en que se muestran. La agrupación no es estética:
# trece entradas planas obligan a leerlas todas para encontrar una.
NAV_GROUPS = [
    ("main", ""),                    # se muestran sueltas, sin desplegable
    ("holdings", "Patrimonio"),
    ("money", "Dinero"),
    ("more", "Más"),
]


@dataclass(frozen=True)
class RelatedLink:
    """Un enlace con su cuenta: «3 estados de cuenta», «$18,430 gastados»."""

    label: str
    count: int
    url: str
    hint: str = ""


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    icon: str = "circle"
    order: int = 100
    section: str = "main"            # main | holdings | money | more


@dataclass(frozen=True)
class DetailTab:
    """Pestana que un modulo aporta a la ficha de otra entidad."""

    resource_kind: str
    key: str
    label: str
    template: str
    order: int = 100


@dataclass(frozen=True)
class DashboardWidget:
    key: str
    label: str
    template: str
    provider: object          # callable(household) -> dict de contexto
    order: int = 100
    size: str = "md"          # sm | md | lg


@dataclass(frozen=True)
class LinkRole:
    """Arista tipada del grafo."""

    key: str
    label: str
    inverse_key: str
    inverse_label: str
    from_kinds: tuple[str, ...] = ()
    to_kinds: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


class Registry:
    def __init__(self):
        self.modules: dict[str, LaresModule] = {}
        self.resource_kinds: dict[str, object] = {}
        self.resource_forms: dict[str, object] = {}
        self.document_types: dict[str, str] = {}
        self.link_roles: dict[str, LinkRole] = {}
        self.obligation_providers: dict[str, ObligationProvider] = {}
        self.checks: dict[str, Check] = {}
        self.nav_items: list[NavItem] = []
        self.detail_tabs: list[DetailTab] = []
        self.widgets: list[DashboardWidget] = []
        self.connectors: dict[str, object] = {}
        self.demo_seeders: list = []
        # De donde saca el motor los sujetos de cada tipo de obligacion.
        # "vehicle" -> los vehiculos activos; "document" -> los que vencen;
        # "household" -> el hogar mismo, para reglas que no cuelgan de nada.
        self.subject_sources: dict[str, object] = {}
        self.classifiers: list = []
        self.related_providers: list = []

    # -- API que usan los modulos -------------------------------------------

    def resource(self, model, kind: str | None = None, form=None):
        """Registra un tipo de recurso y, opcionalmente, su formulario.

        Con el formulario, el nucleo genera las pantallas de alta, edicion y
        ficha sin que el modulo escriba una sola vista. Escribir un CRUD por
        modulo es la forma mas rapida de que cada uno acabe pareciendo distinto.
        """
        kind = kind or getattr(model, "resource_kind", None)
        if not kind:
            raise ImproperlyConfigured(f"{model} no declara resource_kind")
        self.resource_kinds[kind] = model
        if form is not None:
            self.resource_forms[kind] = form
        # Un tipo de recurso es automaticamente una fuente de sujetos: el motor
        # recorre las instancias activas del modelo concreto (no de Resource,
        # que por herencia multi-tabla no traeria los campos de la subclase).
        self.subject_source(kind, lambda household, _m=model: _m.objects.filter(
            status="active", archived_at__isnull=True
        ))
        return model

    def subject_source(self, kind: str, fn):
        """Registra de donde salen los sujetos de un tipo de obligacion.

        `fn(household) -> iterable`. Permite que un modulo genere obligaciones
        sobre algo que no es un Resource (documentos, cuentas, personas) sin
        que el motor tenga que conocerlo.
        """
        self.subject_sources[kind] = fn

    def document_type(self, key: str, label: str):
        self.document_types[key] = label

    def link_role(self, role: LinkRole):
        self.link_roles[role.key] = role

    def obligations(self, *providers):
        for provider in providers:
            instance = provider() if isinstance(provider, type) else provider
            self.obligation_providers[instance.key] = instance

    def check(self, *checks):
        for chk in checks:
            instance = chk() if isinstance(chk, type) else chk
            self.checks[instance.key] = instance

    def nav(self, *items):
        self.nav_items.extend(items)

    def tabs(self, *tabs):
        self.detail_tabs.extend(tabs)

    def widget(self, *widgets):
        self.widgets.extend(widgets)

    def connector(self, key: str, connector):
        self.connectors[key] = connector

    def related(self, fn):
        """Enlaces a lo que cuelga de una entidad.

        `fn(entidad) -> list[RelatedLink]`. Es lo que convierte una ficha en un
        punto de partida: entras en BBVA y ves sus estados de cuenta; entras en
        Diego y ves que le prestaste la guitarra.
        """
        self.related_providers.append(fn)

    def links_for(self, entity) -> list:
        salida = []
        for fn in self.related_providers:
            try:
                salida.extend(fn(entity) or [])
            except Exception:
                logger.exception("Un proveedor de enlaces falló para %s", entity)
        return [link for link in salida if link.count] or []

    def classifier(self, *classifiers):
        """Reconocedores de lo que entra por la bandeja.

        Cada uno mira un InboxItem y, si lo reconoce, devuelve una propuesta.
        Nunca crea nada: eso lo decide la persona.
        """
        for c in classifiers:
            self.classifiers.append(c() if isinstance(c, type) else c)

    def demo_seeder(self, fn):
        """Datos de ejemplo del modulo.

        Existe para que `seed_demo` del nucleo no tenga que importar modulos:
        cada uno siembra lo suyo. `fn(household) -> str` devuelve un resumen.
        """
        self.demo_seeders.append(fn)

    # -- API que usa el nucleo ----------------------------------------------

    def nav_sorted(self, section: str = "main"):
        return sorted(
            (i for i in self.nav_items if i.section == section),
            key=lambda i: (i.order, i.label),
        )

    def nav_grouped(self):
        """El menú, listo para pintar: sueltas primero, luego los desplegables."""
        salida = []
        for clave, etiqueta in NAV_GROUPS:
            items = self.nav_sorted(clave)
            if items:
                salida.append({"key": clave, "label": etiqueta, "items": items})
        return salida

    def tabs_for(self, resource_kind: str):
        return sorted(
            (t for t in self.detail_tabs if t.resource_kind == resource_kind),
            key=lambda t: (t.order, t.label),
        )

    def widgets_sorted(self):
        return sorted(self.widgets, key=lambda w: (w.order, w.label))

    def providers_for(self, kind: str):
        # Coincidencia exacta a proposito: un proveedor sin `applies_to`
        # correria contra todos los sujetos del sistema.
        return [p for p in self.obligation_providers.values() if p.applies_to == kind]


registry = Registry()


# ---------------------------------------------------------------------------
# AppConfig base de un modulo
# ---------------------------------------------------------------------------


class LaresModule(AppConfig):
    """Clase base de todo addon de Lares."""

    # Evita que Django la considere candidata a AppConfig de una app.
    default = False

    # Metadatos del modulo
    label_verbose: str = ""
    version: str = "0.0.1"
    depends: tuple[str, ...] = ()
    icon: str = "package"
    tier: str = "core"       # core | standard | optional  (ver catalogo de features)

    def ready(self):
        self._check_dependencies()
        registry.modules[self.name] = self
        self.register(registry)
        self.connect_signals()
        logger.debug("Modulo Lares registrado: %s v%s", self.name, self.version)

    # -- a implementar por cada modulo --------------------------------------

    def register(self, reg: Registry) -> None:
        """Declara aqui los puntos de extension que aporta el modulo."""

    def connect_signals(self) -> None:
        """Suscribe manejadores al bus de eventos del nucleo."""

    # -- interno -------------------------------------------------------------

    def _check_dependencies(self):
        from django.apps import apps

        for dep in self.depends:
            if not apps.is_installed(dep):
                raise ImproperlyConfigured(
                    f"El modulo '{self.name}' requiere '{dep}', que no esta en INSTALLED_APPS."
                )
