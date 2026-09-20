"""Auditoría de accesos (PRIV-06).

La promesa que ya estaba escrita en `06-privacy-and-security.md` -«el acceso
profesional lleva fecha de caducidad y **todo lo que hace queda en la linea de
tiempo**»- no la cumplia nadie: la linea de tiempo existia como primitiva y
solo escribian en ella cinco sitios.

Se registra aqui y no en cada vista **por la misma razon por la que los
permisos viven en el middleware**: algo de lo que hay que acordarse en cada
pantalla nueva acaba faltando en una, y sera justo en la del saldo. El precio
es que el resumen es la ruta y no una frase bonita; a cambio, no hay forma de
anadir una pantalla que escriba sin que quede registrada.

Que se registra, y que no:

  - **Lo que cambia algo**: toda peticion que no sea de lectura y que acabe
    bien. Un formulario que vuelve con errores no cambio nada, asi que no se
    apunta: una bitacora llena de intentos fallidos no se lee.
  - **Lo que mira quien no es de casa**: las lecturas del contador y del
    invitado, una por pantalla y dia. Registrar cada GET de cada miembro
    convertiria la linea de tiempo en un log de servidor, que es justo lo que
    nadie audita.
  - **Lo que se abre desde fuera**: un enlace compartido o un paquete de
    sucesion. Es el acceso que mas importa, porque es el unico que ocurre sin
    que haya nadie con sesion.

**No se guarda la IP.** Seria el dato forense mas util y es justo el que este
producto no deberia acumular: identifica a quien abre el enlace, que casi
siempre es un familiar.
"""

from __future__ import annotations

import datetime as dt

from ..models import Event

LEER = ("GET", "HEAD", "OPTIONS")

READ = "access.read"
WRITE = "access.write"
OPEN = "access.link"
LOGIN = "access.login"

VERBOS = {
    READ: "Miró",
    WRITE: "Cambió algo",
    OPEN: "Abrieron un enlace",
    LOGIN: "Entró",
}

# Salir no cuenta nada que no cuente el resto, y entrar no es «cambiar algo»:
# es la linea que de verdad se busca cuando alguien revisa una bitacora.
SIN_APUNTAR = {"core:logout"}


def record(request, response) -> None:
    """Lo que haya que apuntar de esta petición. No puede fallar hacia fuera."""
    try:
        if request.method in LEER:
            _read(request)
        else:
            _write(request, response)
    except Exception:  # noqa: BLE001 - auditar no puede tumbar la petición
        import logging

        logging.getLogger(__name__).exception("No se pudo auditar la petición")


def _write(request, response) -> None:
    """Se apunta lo que salió bien.

    El exito es una redireccion: esta aplicacion redirige al guardar y vuelve a
    pintar el formulario con un 200 cuando algo no cuadra. La API contesta JSON,
    asi que ahi vale el 2xx.
    """
    household, user, vista = _quien(request)
    if household is None or user is None:
        return

    if vista in SIN_APUNTAR:
        return

    codigo = response.status_code
    es_json = "json" in response.get("Content-Type", "")
    if not (300 <= codigo < 400 or (es_json and 200 <= codigo < 300)):
        return

    Event.objects.create(
        household=household, verb=LOGIN if vista == "core:login" else WRITE,
        actor=user, source="audit", summary=request.path,
        payload={"view": vista, "method": request.method},
    )


def _read(request) -> None:
    """Solo de quien mira y no toca, y una vez por pantalla y día.

    La marca va en la sesion: sin ella habria que preguntar a la base en cada
    peticion si ya estaba apuntada, que es una consulta por pagina para no
    escribir casi nunca.
    """
    household, user, vista = _quien(request)
    if household is None or user is None or not vista:
        return

    membresia = getattr(request, "membership", None)
    if membresia is None or membresia.can_write:
        return

    hoy = dt.date.today().isoformat()
    vistas = request.session.get("audit") or {}
    if vistas.get(vista) == hoy:
        return

    Event.objects.create(
        household=household, verb=READ, actor=user, source="audit",
        summary=request.path, payload={"view": vista, "role": membresia.role},
    )
    vistas[vista] = hoy
    request.session["audit"] = vistas


def _quien(request):
    household = getattr(request, "household", None)
    user = getattr(request, "user", None)
    if user is not None and not user.is_authenticated:
        user = None
    if household is None and user is not None:
        household = _tras_el_hecho(request, user)
    match = getattr(request, "resolver_match", None)
    return household, user, (match.view_name if match else "")


def _tras_el_hecho(request, user):
    """El hogar de quien acaba de entrar.

    El middleware resuelve el hogar **antes** de la vista, y en la peticion de
    inicio de sesion todavia no hay sesion: `request.household` es None aunque
    al terminar ya haya un usuario dentro. Sin esto, la linea que mas se busca
    en una bitacora -quien entro y cuando- seria justo la que no se apunta.
    """
    from ..models import Membership

    querido = request.session.get("household_id")
    vivas = [
        m for m in Membership.objects.filter(user=user,
                                             accepted_at__isnull=False)
        .select_related("household")
        if m.is_live
    ]
    if not vivas:
        return None
    elegida = next((m for m in vivas if str(m.household_id) == str(querido)),
                   vivas[0])
    return elegida.household


def link_opened(household, subject, label: str, kind: str) -> None:
    """Alguien abrió un enlace de los que se mandan fuera.

    Una vez al dia por enlace: quien lo recibe suele recargar, y veinte lineas
    identicas no cuentan nada que no cuente una.
    """
    from django.utils import timezone

    # `last_seen_at` se guarda en UTC y `today()` es la fecha de casa. A las
    # seis de la tarde en Guadalajara ya es el dia siguiente en UTC, asi que
    # comparar en crudo apunta cada recarga como si fuera de otro dia.
    hoy = dt.date.today()
    visto = getattr(subject, "last_seen_at", None)
    if visto and timezone.localtime(visto).date() == hoy:
        return

    Event.objects.create(
        household=household, verb=OPEN, source="audit", subject=subject,
        summary=label, payload={"kind": kind},
    )


# ---------------------------------------------------------------------------
# Leer la bitácora
# ---------------------------------------------------------------------------


def timeline(household, quien=None, tipo: str = "", limite: int = 200) -> list:
    """La línea de tiempo del hogar, que hasta ahora no se veía en ningún sitio."""
    consulta = Event.objects.filter(household=household).select_related("actor")
    if quien:
        consulta = consulta.filter(actor_id=quien)
    # Las dos preguntas que se le hacen a una bitácora son distintas: «quién ha
    # mirado» y «qué ha cambiado». Un acceso de escritura es de la segunda.
    if tipo == "accesos":
        consulta = consulta.filter(verb__in=[READ, OPEN])
    elif tipo == "cambios":
        consulta = consulta.exclude(verb__in=[READ, OPEN])
    return list(consulta[:limite])


def label_of(event) -> str:
    """Cómo se lee una línea. Los verbos del dominio ya vienen con nombre."""
    if event.verb in VERBOS:
        return VERBOS[event.verb]
    return event.verb.replace(".", " · ")
