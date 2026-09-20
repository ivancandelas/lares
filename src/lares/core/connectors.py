"""Conectores del nucleo: Paperless, correo y carpeta vigilada.

Todos terminan en el mismo sitio -la bandeja- porque la bandeja es la unica
puerta. Un conector que creara documentos directamente se saltaria la
confirmacion humana, que es la regla que sostiene la confianza en todo el
sistema.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from .models import InboxItem
from .services import ingest

logger = logging.getLogger(__name__)

TIMEOUT = 30


@dataclass
class Result:
    fetched: int = 0
    new: int = 0
    error: str = ""


class ConnectorRunner:
    key: str = ""
    label: str = ""
    description: str = ""
    form_class = None

    def run(self, connector) -> Result:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Paperless-ngx
# ---------------------------------------------------------------------------


class PaperlessRunner(ConnectorRunner):
    """Paperless sigue siendo el archivo y el OCR; Lares pone el significado.

    De ahí que se tome su texto ya reconocido en lugar de volver a hacer OCR:
    duplicar ese trabajo sería una dependencia binaria más y el mismo resultado.
    """

    key = "paperless"
    label = "Paperless-ngx"
    description = "Trae los documentos más recientes, con su texto ya reconocido."

    def run(self, connector) -> Result:
        base = (connector.config.get("base_url") or "").rstrip("/")
        token = connector.secret
        if not (base and token):
            return Result(error="Faltan la dirección o el token.")

        limite = int(connector.config.get("page_size") or 25)
        params = {"ordering": "-added", "page_size": limite}
        if tag := connector.config.get("tag"):
            params["tags__name__iexact"] = tag

        url = f"{base}/api/documents/?{urllib.parse.urlencode(params)}"
        try:
            datos = self._get_json(url, token)
        except Exception as exc:
            return Result(error=str(exc)[:400])

        result = Result()
        for doc in datos.get("results", []):
            result.fetched += 1
            _, es_nuevo = self.absorb(connector.household, doc)
            result.new += es_nuevo
        return result

    def absorb(self, household, doc: dict) -> tuple:
        """Mete un documento de Paperless en la bandeja. Devuelve (item, es_nuevo).

        Lo usa tanto el repaso periodico como el webhook, para que los dos
        caminos acaben exactamente en el mismo sitio.

        **No se copia el binario**: se guarda `paperless:<id>` y el texto que
        Paperless ya reconocio. La excepcion es el XML de un CFDI, que no se
        lee sino que se parsea: ahi el archivo lleva informacion que el texto
        plano no tiene -esta firmado- y sin el se perderia la unica fuente que
        no hay que adivinar.
        """
        nombre = doc.get("original_file_name") or f"paperless-{doc['id']}.pdf"
        ref = f"paperless:{doc['id']}"
        texto = (doc.get("content") or "").strip()

        if nombre.lower().endswith(".xml"):
            return self._absorb_xml(household, doc, nombre, ref, texto)

        return ingest.receive_reference(
            household, ref=ref, name=nombre, text=texto,
            source=InboxItem.Source.PAPERLESS,
            mime="application/pdf" if nombre.lower().endswith(".pdf") else "",
        )

    def _absorb_xml(self, household, doc, nombre, ref, texto):
        conector = self._conector(household)
        try:
            contenido = self._get_bytes(
                f"{conector['base']}/api/documents/{doc['id']}/download/",
                conector["token"])
        except Exception:
            logger.warning("No se pudo bajar el XML %s", doc.get("id"))
            return None, False

        item, es_nuevo = ingest.receive(
            household, ContentFile(contenido, name=nombre),
            source=InboxItem.Source.PAPERLESS, note=ref,
        )
        if es_nuevo and not item.external_ref:
            item.external_ref = ref
            item.save(update_fields=["external_ref", "updated_at"])
        return item, es_nuevo

    def _conector(self, household) -> dict:
        from .services import paperless

        conector = paperless.connector_for(household)
        return {
            "base": (conector.config.get("base_url") or "").rstrip("/") if conector else "",
            "token": conector.secret if conector else "",
        }

    def _get_json(self, url, token):
        return json.loads(self._get_bytes(url, token))

    def _get_bytes(self, url, token):
        request = urllib.request.Request(
            url, headers={"Authorization": f"Token {token}"}
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()


# ---------------------------------------------------------------------------
# Correo
# ---------------------------------------------------------------------------


class ImapRunner(ConnectorRunner):
    """Un buzón dedicado al que reenviar lo que importa.

    Con lista blanca de remitentes, siempre. Y el contenido de un correo es
    dato, nunca instrucción: si un adjunto trae texto que parece una orden, se
    le enseña a la persona, no se ejecuta.
    """

    key = "imap"
    label = "Buzón de correo"
    description = "Revisa un buzón y mete los adjuntos de remitentes conocidos."

    ADJUNTOS = (".pdf", ".xml", ".jpg", ".jpeg", ".png", ".csv", ".ofx")

    def run(self, connector) -> Result:
        cfg = connector.config
        host = cfg.get("host")
        usuario = cfg.get("username")
        if not (host and usuario and connector.secret):
            return Result(error="Faltan el servidor, el usuario o la contraseña.")

        permitidos = [s.strip().lower() for s in (cfg.get("allowed_senders") or "").split(",")
                      if s.strip()]
        result = Result()
        try:
            with imaplib.IMAP4_SSL(host, int(cfg.get("port") or 993)) as cliente:
                cliente.login(usuario, connector.secret)
                cliente.select(cfg.get("folder") or "INBOX")
                _, datos = cliente.search(None, "UNSEEN")
                for uid in datos[0].split():
                    _, crudo = cliente.fetch(uid, "(RFC822)")
                    mensaje = email.message_from_bytes(crudo[0][1])
                    if not self._permitido(mensaje, permitidos):
                        continue
                    result.fetched += 1
                    result.new += self._adjuntos(connector, mensaje)
                    cliente.store(uid, "+FLAGS", "\\Seen")
        except Exception as exc:
            return Result(error=str(exc)[:400])
        return result

    def _permitido(self, mensaje, permitidos) -> bool:
        if not permitidos:
            # Sin lista blanca no se acepta nada: un buzón abierto es un agujero.
            return False
        remitente = email.utils.parseaddr(mensaje.get("From", ""))[1].lower()
        return any(remitente.endswith(p) or remitente == p for p in permitidos)

    def _adjuntos(self, connector, mensaje) -> int:
        nuevos = 0
        for parte in mensaje.walk():
            nombre = parte.get_filename()
            if not nombre or not nombre.lower().endswith(self.ADJUNTOS):
                continue
            contenido = parte.get_payload(decode=True)
            if not contenido:
                continue
            archivo = ContentFile(contenido, name=nombre)
            _, es_nuevo = ingest.receive(
                connector.household, archivo, source=InboxItem.Source.EMAIL,
                note=(mensaje.get("Subject") or "")[:300],
            )
            nuevos += es_nuevo
        return nuevos


# ---------------------------------------------------------------------------
# Carpeta vigilada
# ---------------------------------------------------------------------------


class WatchFolderRunner(ConnectorRunner):
    """Una carpeta del NAS donde el escáner deja lo que digitaliza."""

    key = "watchfolder"
    label = "Carpeta vigilada"
    description = "Recoge lo que aparezca en una carpeta del servidor."

    EXTENSIONES = (".pdf", ".xml", ".jpg", ".jpeg", ".png", ".csv", ".ofx", ".txt")

    def run(self, connector) -> Result:
        ruta = Path(connector.config.get("path") or "")
        if not ruta.is_dir():
            return Result(error=f"No existe la carpeta {ruta}")

        result = Result()
        for archivo in sorted(ruta.iterdir()):
            if not archivo.is_file() or archivo.suffix.lower() not in self.EXTENSIONES:
                continue
            result.fetched += 1
            contenido = archivo.read_bytes()
            _, es_nuevo = ingest.receive(
                connector.household,
                ContentFile(contenido, name=archivo.name),
                source=InboxItem.Source.WATCH,
                note=str(archivo),
            )
            result.new += es_nuevo
            # El original se deja donde está: lo que se mueve solo se pierde.
            if es_nuevo and connector.config.get("delete_after"):
                archivo.unlink(missing_ok=True)
        return result


def checksum(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def run_connector(connector) -> Result:
    """Ejecuta un conector y deja constancia de cómo fue."""
    from .registry import registry

    runner = registry.connectors.get(connector.key)
    if not runner:
        result = Result(error=f"No hay conector «{connector.key}»")
    else:
        try:
            result = runner.run(connector)
        except Exception as exc:
            logger.exception("El conector %s falló", connector.key)
            result = Result(error=str(exc)[:400])

    connector.last_run_at = timezone.now()
    connector.last_count = result.new
    connector.last_error = result.error
    connector.save(update_fields=["last_run_at", "last_count", "last_error", "updated_at"])
    return result
