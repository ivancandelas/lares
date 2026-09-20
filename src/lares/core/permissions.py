"""A qué ámbito pertenece cada pantalla, y quién puede abrirla.

La regla general es que **el ambito de una pantalla es el modulo que la
publica**: todo lo de `finance:` es dinero, todo lo de `vehicles:` es coches.
Eso sale gratis del espacio de nombres de las URL y no hay que mantener nada.

La excepcion es el nucleo. `core:` publica cosas de dominios muy distintos -la
bandeja, los documentos, las personas- y ademas algunas pantallas de dinero que
viven ahi porque las usan varios modulos: registrar un gasto, quien debe a
quien, los pagos recurrentes. Esas hay que clasificarlas a mano, y por eso
existe este archivo.

Lo que se protege aqui es **el acceso a la pantalla**, con un 403 de verdad.
Esconder una entrada del menu no es un permiso: la direccion se puede teclear.
"""

from __future__ import annotations

# Pantallas del núcleo que pertenecen a un dominio concreto. Lo que no esté
# aquí es del núcleo y lo ve cualquier miembro del hogar.
AMBITO_DE_RUTA = {
    # Dinero
    "core:owed": "finance",
    "core:rules": "finance",
    "core:rule-new": "finance",
    "core:rule-toggle": "finance",
    "core:expense-new": "finance",
    "core:income-new": "finance",
    "core:transfer-new": "finance",
    "core:account-new": "finance",
    # Personas y lo que se comparte. Un vCard saca la agenda entera de golpe,
    # así que pesa más que la pantalla desde la que se pide.
    "core:parties": "people",
    "core:responsibilities": "people",
    "core:obligation-assign": "people",
    "core:contact-points": "people",
    "core:contact-point-delete": "people",
    "core:contacts-vcf": "people",
    "core:party-vcf": "people",
    "core:tag-vcf": "people",
    "core:party-new": "people",
    "core:party-detail": "people",
    "core:party-edit": "people",
    "core:party-vcard": "people",
    "core:shares": "people",
    "core:share-new": "people",
    "core:share-revoke": "people",
    # Administración del hogar
    "core:connectors": "admin",
    "core:connector-new": "admin",
    "core:connector-edit": "admin",
    "core:connector-run": "admin",
    "core:api-webhooks": "admin",
    "core:household": "admin",
    "core:household-edit": "admin",
    "core:audit": "admin",
    "core:member-invite": "admin",
    "core:member-edit": "admin",
    "core:member-remove": "admin",
    "core:calendar-settings": "admin",
    # Sucesión: decide a quién se le abre todo el hogar el peor día. Eso lo
    # toca quien administra, y nadie más.
    "core:succession": "admin",
    "core:successor-new": "admin",
    "core:successor-edit": "admin",
    "core:successor-toggle": "admin",
    "core:succession-here": "admin",
    "core:succession-preview": "admin",
}

# Rutas que se abren con un token y no con una membresía. Cada una valida el
# suyo: el feed del calendario, un enlace compartido, la invitación. Entran
# aquí porque un miembro con sesión iniciada también puede pedirlas y no hay
# que medirlas contra sus ámbitos.
LIBRES = {
    "core:invite-accept",
    "core:household-switch",
    "core:logout",
    "core:login",
    "core:calendar-feed",
    "core:manifest",
    "core:service-worker",
    # Las comprueba Docker y la actualización, sin sesión y sin llave.
    "core:health",
    "core:health-db",
    "core:shared",
    "core:shared-vcf",
    "core:succession-package",
    "core:succession-download",
    "core:succession-json",
    "core:succession-document",
}

# La API devuelve lo mismo que las pantallas, así que se mide igual. Va por
# ámbito y no en bloque porque la agenda y los documentos no son el dinero.
AMBITO_DE_API = {
    "core:api-agenda": "core",
    "core:api-obligations": "core",
    "core:api-obligation-complete": "core",
    "core:api-documents": "core",
    "core:api-resources": "core",
    "core:api-gaps": "core",
    "core:api-search": "core",
    # Entra por llave de API, no por sesión: es Paperless quien llama.
    "core:api-inbox-paperless": "core",
}


def scope_of(url_name: str, namespace: str) -> str:
    """El ámbito de una pantalla: su módulo, salvo las del núcleo."""
    if url_name in AMBITO_DE_RUTA:
        return AMBITO_DE_RUTA[url_name]
    if url_name in AMBITO_DE_API:
        return AMBITO_DE_API[url_name]
    return namespace or "core"


def scopes_available(registry) -> list:
    """Los ámbitos que se pueden conceder, para el formulario de miembro."""
    modulos = sorted(
        {(m.label, m.label_verbose) for m in registry.modules.values()}
    )
    propios = [("people", "Personas y contactos"),
               ("admin", "Administración del hogar")]
    return modulos + propios


def can_open(membership, url_name: str, namespace: str, method: str) -> bool:
    """Si esta persona puede abrir esta pantalla ahora mismo."""
    if membership is None:
        return False
    if url_name in LIBRES:
        return True
    if not membership.is_live:
        return False

    ambito = scope_of(url_name, namespace)
    if ambito == "admin" and not membership.can_admin:
        return False
    if not membership.sees(ambito):
        return False
    # Mirar no es registrar: el contador y el invitado no escriben.
    return not (method not in ("GET", "HEAD", "OPTIONS")
                and not membership.can_write)


def scope_of_obligation(obligation) -> str:
    """A qué dominio pertenece un vencimiento.

    Sale de `source`, que ya viene con el nombre del módulo delante:
    `vehicles.verificacion`, `taxes.monthly`, `finance.card_payment`. Es la
    misma convención que usan las claves de los huecos, así que se filtra con
    el mismo criterio y no hay nada nuevo que mantener.

    Las de un pack de jurisdicción llevan `packs.<tipo de recurso>`, y el tipo
    sí sabe de qué módulo es: el refrendo de un coche es de los coches, aunque
    la regla venga de un YAML.
    """
    prefijo, _, resto = (obligation.source or "").partition(".")
    if prefijo == "packs" and resto:
        from .registry import registry

        modelo = registry.resource_kinds.get(resto)
        if modelo is not None:
            return modelo._meta.app_label
    return prefijo or "core"


def visible_obligations(obligations, membership) -> list:
    """Los vencimientos que esta persona puede ver.

    Un título ya cuenta de más: «Tarjeta ****9876, pago mínimo» en la pantalla
    de alguien que no ve el dinero es una fuga aunque no pueda abrir nada. Es
    exactamente el mismo argumento que ya se aplicaba al menú y a los huecos
    del tablero; lo que faltaba era aplicarlo a la lista de lo que vence.
    """
    permitidos = visible_scopes(membership)
    if permitidos is None:
        return list(obligations)
    return [o for o in obligations
            if scope_of_obligation(o) in permitidos]


def visible_scopes(membership) -> set | None:
    """Los ámbitos que esta persona ve. None significa «todos»."""
    if membership is None:
        return set()
    if membership.sees_everything:
        return None
    ambitos = set(membership.scopes or [])
    if membership.can_admin:
        ambitos.add("admin")
    return ambitos | {"core"}
