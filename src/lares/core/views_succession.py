"""Sucesión y emergencia: el interruptor y el paquete.

Dos publicos muy distintos en el mismo archivo:

  - el titular, que configura a quien se le libera que y despues de cuanto
    silencio, y que necesita ver exactamente lo que se entregara;
  - quien recibe el enlace, que entra sin sesion, el peor dia de su ano, y
    tiene que entender en diez segundos que hacer.

La segunda pantalla es la que manda en las decisiones de diseno.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import Document, EmergencyContact
from .scoping import use_household
from .services import audit, paperless, succession

# ---------------------------------------------------------------------------
# El titular
# ---------------------------------------------------------------------------


def succession_home(request):
    """Quién recibe qué si dejas de entrar."""
    contactos = list(EmergencyContact.objects.all().select_related("party"))
    silencio = succession.days_quiet(request.household)

    return render(request, "core/succession.html", {
        "contactos": contactos,
        "silencio": silencio,
        "ultimo": succession.last_seen(request.household),
        "abiertos": [c for c in contactos if c.state != EmergencyContact.State.ARMED
                     and c.state != EmergencyContact.State.OFF],
        "secciones": succession.SECCIONES,
    })


def contact_new(request):
    from .forms import EmergencyContactForm

    form = EmergencyContactForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        contacto = form.save()
        messages.success(
            request,
            f"{contacto.who} recibirá el paquete si no entras en "
            f"{contacto.quiet_days} días. Antes te avisamos.")
        return redirect("core:succession")

    return render(request, "core/form.html", {
        "form": form, "title": "Un contacto de emergencia",
        "submit": "Guardar", "cancel_url": "core:succession",
    })


def contact_edit(request, pk):
    from .forms import EmergencyContactForm

    contacto = get_object_or_404(EmergencyContact, pk=pk)
    form = EmergencyContactForm(request.POST or None, instance=contacto,
                                household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cambios guardados.")
        return redirect("core:succession")

    return render(request, "core/form.html", {
        "form": form, "title": contacto.who, "submit": "Guardar",
        "cancel_url": "core:succession",
    })


def contact_toggle(request, pk):
    """Desactivar o volver a armar. No borra: el rastro de lo que pasó se queda."""
    contacto = get_object_or_404(EmergencyContact, pk=pk)
    if contacto.state == EmergencyContact.State.OFF:
        contacto.state = EmergencyContact.State.ARMED
        aviso = f"{contacto.who} vuelve a estar armado."
    else:
        contacto.state = EmergencyContact.State.OFF
        contacto.token = ""
        contacto.warned_on = None
        contacto.released_at = None
        aviso = f"{contacto.who} ya no recibirá nada."
    contacto.save(update_fields=["state", "token", "warned_on", "released_at",
                                 "updated_at"])
    messages.success(request, aviso)
    return redirect("core:succession")


def im_here(request):
    """«Sigo aquí»: cancela los avisos y revoca lo que se haya liberado."""
    cuantos = succession.im_here(request.household)
    if cuantos:
        messages.success(
            request, f"Listo: {cuantos} acceso{'s' if cuantos != 1 else ''} "
                     "vuelve a estar cerrado.")
    else:
        messages.success(request, "No había nada abierto. El contador vuelve a cero.")
    return redirect("core:succession")


def package_preview(request, pk):
    """Lo que verá esa persona, tal cual, antes de que sirva para nada.

    Sin esto nadie activa el mecanismo: pedir que confies en que un dia se
    entregara «lo correcto» sin poder mirarlo es pedir demasiado.
    """
    contacto = get_object_or_404(EmergencyContact, pk=pk)
    datos = succession.package(request.household, contacto)
    return render(request, "core/succession_package.html", {
        **datos, "preview": True,
    })


# ---------------------------------------------------------------------------
# Quien recibe el enlace
# ---------------------------------------------------------------------------


def _por_token(token) -> EmergencyContact:
    contacto = EmergencyContact.all_objects.filter(token=token).first() if token else None
    if contacto is None or not contacto.is_live:
        raise Http404("Ese enlace no existe o dejó de funcionar.")
    return contacto


@login_not_required
def package_view(request, token):
    contacto = _por_token(token)
    datos = succession.package(contacto.household, contacto)
    audit.link_opened(contacto.household, contacto,
                      f"Paquete de sucesión de {contacto.who}", "succession")
    contacto.touch()
    return render(request, "core/succession_package.html", {
        **datos, "preview": False, "token": token,
    })


@login_not_required
def package_download(request, token):
    """El paquete en un zip, para guardarlo fuera de aquí.

    Un enlace que solo funciona mientras la instalacion siga en pie no es una
    sucesion: el dia que alguien deje de pagar el servidor, esto tiene que
    seguir existiendo en el disco de quien lo recibio.
    """
    contacto = _por_token(token)
    datos = succession.package(contacto.household, contacto)
    audit.link_opened(contacto.household, contacto,
                      f"Paquete de {contacto.who} (descarga)", "succession")
    contacto.touch()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("paquete.json",
                    json.dumps(succession.as_json(datos), indent=2,
                               ensure_ascii=False, default=str))
        zf.writestr("LEEME.txt", _leeme(datos))
        for entrada in datos.get("documentos", []):
            if not entrada["abierto"]:
                continue
            doc = entrada["doc"]
            if entrada.get("fuera"):
                # Vive en Paperless: se trae ahora, que es cuando tiene que
                # sobrevivir a esta instalación.
                contenido = paperless.materialize(contacto.household, doc)
                if contenido:
                    zf.writestr(f"documentos/{paperless.filename_for(doc)}",
                                contenido)
                continue
            try:
                with doc.file.open("rb") as f:
                    zf.writestr(f"documentos/{doc.file.name.split('/')[-1]}",
                                f.read())
            except (OSError, ValueError):
                # Un binario que ya no está no puede tumbar la descarga: lo
                # demás del paquete sigue valiendo.
                continue

    buffer.seek(0)
    nombre = f"sucesion-{contacto.household.slug}-{dt.date.today():%Y-%m-%d}.zip"
    respuesta = FileResponse(buffer, content_type="application/zip")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


@login_not_required
def package_document(request, token, pk):
    """Un documento del paquete. Solo los que no son confidenciales."""
    contacto = _por_token(token)
    with use_household(contacto.household):
        doc = get_object_or_404(Document, pk=pk)
        fuera = bool(paperless.doc_id(doc.external_ref))
        if (doc.confidentiality != Document.Confidentiality.NORMAL
                or not (doc.file or fuera)
                or "documentos" not in succession.secciones_de(contacto)):
            raise Http404("Ese documento no va en este paquete.")

        if fuera:
            contenido = paperless.materialize(contacto.household, doc)
            if contenido is None:
                return HttpResponse(
                    "Ese archivo vive en Paperless y ahora no responde. "
                    "Inténtalo más tarde o pide el paquete completo.",
                    content_type="text/plain; charset=utf-8", status=502)
            respuesta = HttpResponse(contenido, content_type="application/pdf")
            respuesta["Content-Disposition"] = \
                f'attachment; filename="{paperless.filename_for(doc)}"'
            return respuesta

        return FileResponse(doc.file.open("rb"), as_attachment=True,
                            filename=doc.file.name.split("/")[-1])


def _leeme(datos: dict) -> str:
    con_archivo = any(d["abierto"] for d in datos.get("documentos", []))
    lineas = [
        f"Paquete de sucesión de {datos['household'].name}",
        f"Generado el {datos['hoy']:%d/%m/%Y}",
        "",
        "Esto no es todo el sistema: es lo que el titular eligió que",
        "necesitarías. `paquete.json` lleva los datos en un formato que se",
        "puede leer sin este programa",
    ]
    lineas[-1] += ("; en `documentos/` están los archivos que se entregan."
                   if con_archivo else ".")
    lineas += ["", "Qué hacer:"]
    for i, paso in enumerate(datos.get("pasos", []), 1):
        lineas.append(f"  {i}. {paso['titulo']} — {paso['detalle']}")
    if datos.get("contacto") and datos["contacto"].note:
        lineas += ["", "Te dejó dicho:", "", f"    {datos['contacto'].note}"]
    return "\n".join(lineas) + "\n"


@login_not_required
def package_json(request, token):
    """El mismo paquete, en JSON, para quien prefiera la máquina."""
    contacto = _por_token(token)
    datos = succession.package(contacto.household, contacto)
    contacto.touch()
    cuerpo = json.dumps(succession.as_json(datos), indent=2,
                        ensure_ascii=False, default=str)
    return HttpResponse(cuerpo, content_type="application/json; charset=utf-8")
