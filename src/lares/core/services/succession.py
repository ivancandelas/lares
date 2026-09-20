"""El paquete de sucesion y el interruptor que lo libera.

Dos cosas que se apoyan una en la otra:

  - **El paquete** (PRIV-05). Lo que un tercero necesita para hacerse cargo: a
    quien llamar, que documentos existen y donde, que se paga cada mes, que se
    debe y que vence. No es la exportacion completa: eso es portabilidad, y
    entregarla entera no es sucesion sino una copia de la llave de casa.
  - **El acceso diferido** (PRIV-04). Si el titular deja de entrar N dias, se
    avisa y se abre una ventana de gracia; si el silencio sigue, se libera.

Aqui no se guarda nada del paquete: se arma en el momento a partir de lo que ya
hay, igual que `owed` y `recurring`. Un paquete guardado es una copia que
envejece, y la copia que envejece es justo la que se lee el peor dia.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import (
    ContactPoint,
    Document,
    EmergencyContact,
    Membership,
    Party,
    Resource,
    lares_event,
)
from ..registry import registry
from ..scoping import use_household

logger = logging.getLogger(__name__)


# Las secciones del paquete. Son fijas y del nucleo a proposito: cada una
# contesta una pregunta que se hace el dia que esto se abre, y ninguna depende
# de que modulos haya instalados.
SECCIONES = [
    ("personas", "A quién llamar"),
    ("documentos", "Dónde están los papeles"),
    ("patrimonio", "Qué hay"),
    ("recurrentes", "Qué se paga cada mes"),
    ("deudas", "Qué se debe y a quién"),
    ("obligaciones", "Qué vence pronto"),
]

TODAS = [clave for clave, _ in SECCIONES]


def secciones_de(contacto) -> list[str]:
    """Las que lleva este paquete. Vacío significa todas, como los ámbitos."""
    elegidas = [s for s in (contacto.sections or []) if s in TODAS]
    return elegidas or TODAS


# ---------------------------------------------------------------------------
# El silencio del titular
# ---------------------------------------------------------------------------


def last_seen(household) -> dt.date | None:
    """El último día que entró alguien que administra el hogar.

    Se mide sobre quien administra y no sobre cualquier miembro: que el hijo
    siga apuntando sus tareas no dice nada sobre el titular, que es de quien
    habla este mecanismo.

    `None` significa que no hay medida -nadie ha entrado nunca desde que se
    lleva la cuenta- y entonces no se libera nada. Un sistema que interpreta la
    falta de dato como "se murio" es peor que no tener el mecanismo.
    """
    fechas = []
    for m in Membership.objects.filter(
        household=household, role__in=Membership.ADMINISTRAN,
        accepted_at__isnull=False,
    ).select_related("user"):
        if m.last_seen_on:
            fechas.append(m.last_seen_on)
        elif m.user.last_login:
            fechas.append(timezone.localtime(m.user.last_login).date())
    return max(fechas) if fechas else None


def days_quiet(household, on_date: dt.date | None = None) -> int | None:
    on_date = on_date or dt.date.today()
    visto = last_seen(household)
    return (on_date - visto).days if visto else None


# ---------------------------------------------------------------------------
# El interruptor
# ---------------------------------------------------------------------------


def review(household, on_date: dt.date | None = None) -> dict:
    """Avisa, libera o rearma. Idempotente: se puede correr cien veces al día.

    El orden importa: **volver cancela**. Si el titular entró, lo primero que
    pasa es que lo avisado se rearma y lo liberado se revoca, antes de mirar
    ningún plazo.
    """
    on_date = on_date or dt.date.today()
    silencio = days_quiet(household, on_date)
    salida = {"avisados": 0, "liberados": 0, "rearmados": 0,
              "silencio": silencio}
    if silencio is None:
        return salida

    with use_household(household):
        vivos = EmergencyContact.objects.exclude(state=EmergencyContact.State.OFF)
        for contacto in vivos:
            if silencio < contacto.quiet_days:
                if contacto.state != EmergencyContact.State.ARMED:
                    rearm(contacto)
                    salida["rearmados"] += 1
                continue
            if contacto.state == EmergencyContact.State.ARMED:
                warn(contacto, on_date)
                salida["avisados"] += 1
            elif (contacto.state == EmergencyContact.State.WARNED
                    and contacto.releases_on and on_date >= contacto.releases_on):
                release(contacto)
                salida["liberados"] += 1
    return salida


def warn(contacto, on_date: dt.date | None = None):
    """Abre la ventana de gracia y avisa al titular por todos los canales.

    El aviso va al titular, no al contacto: todavia no hay nada que entregar y
    decirle a alguien "te van a dar acceso a los datos de tu hermano" cuando el
    hermano esta de viaje es una llamada telefonica desagradable y evitable.
    """
    contacto.state = EmergencyContact.State.WARNED
    contacto.warned_on = on_date or dt.date.today()
    contacto.save(update_fields=["state", "warned_on", "updated_at"])

    _avisar_al_titular(contacto)
    lares_event.send(
        "core", household=contacto.household, verb="succession.warned",
        subject=contacto,
        summary=(f"{contacto.who}: se avisó del acceso diferido, se libera el "
                 f"{contacto.releases_on:%d/%m/%Y}"),
        payload={"releases_on": str(contacto.releases_on)},
    )


def release(contacto):
    """Libera el paquete y le manda el enlace al contacto."""
    contacto.open_link()
    contacto.state = EmergencyContact.State.RELEASED
    contacto.released_at = timezone.now()
    contacto.save(update_fields=["token", "state", "released_at", "updated_at"])

    _avisar_al_contacto(contacto)
    lares_event.send(
        "core", household=contacto.household, verb="succession.released",
        subject=contacto,
        summary=f"{contacto.who}: se liberó el paquete de sucesión",
    )


def rearm(contacto):
    """Volver lo cierra: se rearma lo avisado y se revoca lo liberado.

    Quien vuelve a entrar esta vivo, y entonces el enlace deja de funcionar en
    el acto. Queda en la linea de tiempo: si alguien abrio el paquete, eso ya
    paso y hay que poder verlo.
    """
    estaba = contacto.state
    contacto.state = EmergencyContact.State.ARMED
    contacto.warned_on = None
    contacto.released_at = None
    contacto.token = ""
    contacto.save(update_fields=["state", "warned_on", "released_at", "token",
                                 "updated_at"])

    lares_event.send(
        "core", household=contacto.household, verb="succession.rearmed",
        subject=contacto,
        summary=(f"{contacto.who}: volviste a entrar, "
                 + ("el paquete dejó de funcionar"
                    if estaba == EmergencyContact.State.RELEASED
                    else "el aviso se canceló")),
    )


def im_here(household) -> int:
    """«Sigo aquí»: rearma todo a mano, sin esperar a la tarea de fondo."""
    con = 0
    with use_household(household):
        for contacto in EmergencyContact.objects.exclude(
            state__in=[EmergencyContact.State.ARMED, EmergencyContact.State.OFF]
        ):
            rearm(contacto)
            con += 1
    return con


# ---------------------------------------------------------------------------
# Los avisos
# ---------------------------------------------------------------------------


def _url(ruta: str) -> str:
    return f"{settings.SITE_URL.rstrip('/')}{ruta}"


def _enviar(asunto_tpl, cuerpo_tpl, contexto, destinos) -> bool:
    if not destinos:
        return False
    try:
        send_mail(
            subject=render_to_string(asunto_tpl, contexto).strip(),
            message=render_to_string(cuerpo_tpl, contexto),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=destinos,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("No se pudo enviar el aviso de sucesión")
        return False


def _avisar_al_titular(contacto) -> bool:
    destinos = list(
        Membership.objects.filter(household=contacto.household,
                                  role__in=Membership.ADMINISTRAN,
                                  accepted_at__isnull=False)
        .values_list("user__email", flat=True)
    )
    return _enviar(
        "core/email/succession_warn_subject.txt",
        "core/email/succession_warn_body.txt",
        {"contacto": contacto, "household": contacto.household,
         "product_name": settings.PRODUCT_NAME, "url": _url("/sucesion/")},
        destinos,
    )


def _avisar_al_contacto(contacto) -> bool:
    destino = contacto.where
    return _enviar(
        "core/email/succession_release_subject.txt",
        "core/email/succession_release_body.txt",
        {"contacto": contacto, "household": contacto.household,
         "product_name": settings.PRODUCT_NAME,
         "url": _url(f"/sucesion/{contacto.token}/")},
        [destino] if destino else [],
    )


# ---------------------------------------------------------------------------
# El paquete
# ---------------------------------------------------------------------------


def package(household, contacto=None, sections=None) -> dict:
    """Lo que ve quien recibe el paquete, armado en el momento.

    `contacto` puede ser None: es la vista previa que ve el titular antes de
    que esto le sirva a nadie. Enseñar exactamente lo que se entregará es lo
    que hace que alguien se atreva a activarlo.
    """
    claves = sections or (secciones_de(contacto) if contacto else TODAS)
    hoy = dt.date.today()

    with use_household(household):
        datos = {
            "household": household,
            "contacto": contacto,
            "hoy": hoy,
            "secciones": claves,
            "titular": Party.objects.filter(is_self=True).first(),
        }
        if "personas" in claves:
            datos["personas"] = _personas()
        if "documentos" in claves:
            datos["documentos"] = _documentos()
        if "patrimonio" in claves:
            datos["patrimonio"] = _patrimonio()
        if "recurrentes" in claves:
            datos["recurrentes"] = _recurrentes(household)
        if "deudas" in claves:
            datos["deudas"] = registry.owed_all(household)
        if "obligaciones" in claves:
            from .agenda import week_ahead

            datos["obligaciones"] = week_ahead(household)

    datos["pasos"] = _pasos(datos)
    return datos


def _personas() -> list:
    """A quién llamar, con sus teléfonos y correos delante.

    Van personas y organizaciones juntas: el dia que esto se abre, la
    aseguradora y el hermano son la misma pregunta.
    """
    puntos = {}
    for punto in ContactPoint.objects.select_related("party"):
        puntos.setdefault(punto.party_id, []).append(punto)
    gente = []
    for party in Party.objects.filter(archived_at__isnull=True):
        contactos = puntos.get(party.pk, [])
        if contactos or party.kind == Party.Kind.PERSON:
            gente.append({"party": party, "puntos": contactos})
    return gente


def _documentos() -> list:
    """Los papeles. Lo confidencial se nombra pero no se abre.

    Un documento privado o secreto sigue apareciendo en la lista -saber que
    existe una escritura es la mitad del valor- pero el binario no se entrega
    por este enlace.
    """
    from . import paperless

    salida = []
    for doc in Document.objects.filter(archived_at__isnull=True).select_related("issuer"):
        fuera = bool(paperless.doc_id(doc.external_ref))
        if doc.confidentiality != Document.Confidentiality.NORMAL:
            nota = "no se entrega por este enlace"
        elif not (doc.file or fuera):
            # No es lo mismo que negarlo: aqui solo esta anotado que existe, y
            # quien lo lea tiene que salir a buscar el papel.
            nota = "está registrado, no escaneado"
        else:
            nota = ""
        # Lo que vive en Paperless tambien se entrega: se trae al empaquetar.
        # Un paquete de sucesion que solo funciona mientras el servidor de casa
        # siga encendido no es una sucesion.
        salida.append({"doc": doc, "abierto": not nota, "nota": nota,
                       "fuera": fuera})
    return salida


def _patrimonio() -> list:
    grupos = {}
    for recurso in Resource.objects.filter(status=Resource.Status.ACTIVE):
        grupos.setdefault(recurso.kind or "otros", []).append(recurso)
    return [{"kind": kind, "label": _etiqueta(kind), "items": items}
            for kind, items in sorted(grupos.items())]


def _etiqueta(kind: str) -> str:
    modelo = registry.resource_kinds.get(kind)
    return modelo._meta.verbose_name_plural.capitalize() if modelo else kind


def _recurrentes(household) -> dict:
    todos = [r for r in registry.recurring_all(household) if r.is_active]
    salen = [r for r in todos if not r.is_income]
    entran = [r for r in todos if r.is_income]
    return {
        "salen": salen,
        "entran": entran,
        "al_mes": sum(r.per_month or 0 for r in salen),
    }


def _pasos(datos: dict) -> list:
    """El checklist «qué hacer si». No es un documento suelto: sale de los datos.

    Un playbook escrito a mano envejece en cuanto cambia una poliza. Estos
    pasos cuentan lo que hay ahora mismo, y por eso no hace falta mantenerlos.
    """
    pasos = []
    gente = datos.get("personas") or []
    if gente:
        pasos.append({
            "titulo": "Avisa a quien toca",
            "detalle": (f"Hay {len(gente)} contacto{'s' if len(gente) != 1 else ''} "
                        "con teléfono o correo en la lista."),
        })
    docs = datos.get("documentos") or []
    if docs:
        vencen = sum(1 for d in docs if d["doc"].expires_on)
        pasos.append({
            "titulo": "Reúne los papeles",
            "detalle": (f"{len(docs)} documento{'s' if len(docs) != 1 else ''} "
                        f"registrados, {vencen} con fecha de vencimiento."),
        })
    moneda = datos["household"].currency
    recurrentes = datos.get("recurrentes") or {}
    if recurrentes.get("salen"):
        pasos.append({
            "titulo": "Decide qué se cancela y qué se mantiene",
            "detalle": (f"{len(recurrentes['salen'])} cobros recurrentes, "
                        f"unos {recurrentes['al_mes']:,.0f} {moneda} al mes. "
                        "La luz y el agua se mantienen; lo demás se revisa."),
        })
    deudas = datos.get("deudas") or []
    if deudas:
        deben = sum(d.amount or 0 for d in deudas if d.is_incoming)
        debe = sum(d.amount or 0 for d in deudas if not d.is_incoming)
        pasos.append({
            "titulo": "Cobra lo que le deben y paga lo que debe",
            "detalle": f"Le deben {deben:,.0f} {moneda}; debe {debe:,.0f} {moneda}.",
        })
    agenda = datos.get("obligaciones") or {}
    if agenda.get("overdue") or agenda.get("this_week"):
        pasos.append({
            "titulo": "Atiende lo que ya vence",
            "detalle": (f"{len(agenda.get('overdue', []))} vencidas y "
                        f"{len(agenda.get('this_week', []))} esta semana."),
        })
    return pasos


def as_json(datos: dict) -> dict:
    """El paquete en un formato que se pueda guardar y leer sin Lares.

    Lo que se entrega tiene que sobrevivir a la instalacion: si para leer esto
    hay que levantar un Django, el paquete no sirve el dia que sirve.
    """
    salida = {
        "formato": "lares-sucesion/1",
        "hogar": datos["household"].name,
        "fecha": str(datos["hoy"]),
        "para": datos["contacto"].who if datos.get("contacto") else "",
        "nota": datos["contacto"].note if datos.get("contacto") else "",
        "pasos": datos["pasos"],
        "secciones": datos["secciones"],
    }
    if "personas" in datos:
        salida["personas"] = [
            {"nombre": p["party"].name,
             "tipo": p["party"].get_kind_display(),
             "contacto": [{"canal": c.get_channel_display(), "valor": c.value}
                          for c in p["puntos"]]}
            for p in datos["personas"]
        ]
    if "documentos" in datos:
        salida["documentos"] = [
            {"titulo": d["doc"].title,
             "tipo": d["doc"].doc_type,
             "emisor": str(d["doc"].issuer) if d["doc"].issuer_id else "",
             "vence": str(d["doc"].expires_on) if d["doc"].expires_on else "",
             "archivo": d["doc"].file.name if d["abierto"] else ""}
            for d in datos["documentos"]
        ]
    if "patrimonio" in datos:
        salida["patrimonio"] = [
            {"tipo": g["label"],
             "cosas": [{"nombre": r.name,
                        "valor": float(r.current_value or r.purchase_amount or 0)}
                       for r in g["items"]]}
            for g in datos["patrimonio"]
        ]
    if "recurrentes" in datos:
        salida["recurrentes"] = [
            {"titulo": r.title, "importe": float(r.amount or 0),
             "cada": r.cycle_label, "sentido": "cobro" if r.is_income else "pago"}
            for r in datos["recurrentes"]["salen"] + datos["recurrentes"]["entran"]
        ]
    if "deudas" in datos:
        salida["deudas"] = [
            {"titulo": d.title, "importe": float(d.amount or 0),
             "sentido": "le deben" if d.is_incoming else "debe",
             "con": str(d.counterparty) if d.counterparty else ""}
            for d in datos["deudas"]
        ]
    if "obligaciones" in datos:
        agenda = datos["obligaciones"]
        salida["obligaciones"] = [
            {"titulo": o.title, "vence": str(o.due_on),
             "importe": float(o.amount or 0)}
            for o in agenda["overdue"] + agenda["this_week"] + agenda["later"]
        ]
    return salida
