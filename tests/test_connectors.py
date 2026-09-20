"""Conectores: lo que llega solo.

Lo importante no es hablar con Paperless: es que todo lo que traigan acabe en
la bandeja y espere a una persona, igual que si lo hubieras arrastrado tú.
"""

import json
import pathlib
from unittest import mock

import pytest

from lares.core.connectors import (
    ImapRunner,
    PaperlessRunner,
    WatchFolderRunner,
    run_connector,
)
from lares.core.models import Connector, Document, InboxItem
from lares.core.services.secrets_store import decrypt, encrypt

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CFDI_XML = (FIXTURES / "cfdi_ejemplo.xml").read_bytes()


# --- Secretos ---------------------------------------------------------------


def test_un_secreto_no_queda_legible():
    cifrado = encrypt("token-super-secreto")

    assert "token-super-secreto" not in cifrado
    assert decrypt(cifrado) == "token-super-secreto"


def test_el_mismo_secreto_no_se_cifra_igual_dos_veces():
    assert encrypt("igual") != encrypt("igual")


@pytest.mark.django_db
def test_el_token_no_se_guarda_en_claro_en_la_base(scoped):
    connector = Connector.objects.create(
        household=scoped, key="paperless", label="Casa"
    )
    connector.secret = "token-abc-123"
    connector.save()
    connector.refresh_from_db()

    assert "token-abc-123" not in connector.secret_encrypted
    assert connector.secret == "token-abc-123"
    assert connector.has_secret


# --- Paperless --------------------------------------------------------------


@pytest.fixture
def paperless(scoped):
    connector = Connector.objects.create(
        household=scoped, key="paperless", label="Paperless de casa",
        config={"base_url": "https://paperless.test", "page_size": 10},
    )
    connector.secret = "token"
    connector.save()
    return connector


@pytest.mark.django_db
def test_trae_documentos_de_paperless_sin_copiar_el_binario(paperless):
    """Paperless es el archivo; Lares, el significado.

    Copiar el PDF dejaría dos repositorios documentales sin que nadie lo
    hubiera decidido, y el doble de gigas para el mismo papel.
    """
    listado = json.dumps({"results": [{
        "id": 42, "original_file_name": "poliza_mazda.pdf",
        "content": "Póliza de cobertura amplia del Mazda",
    }]}).encode()

    runner = PaperlessRunner()
    with mock.patch.object(runner, "_get_bytes", side_effect=[listado]) as trae:
        result = runner.run(paperless)

    assert result.new == 1
    # Una sola llamada: la del listado. El binario no se baja.
    assert trae.call_count == 1

    item = InboxItem.objects.get()
    assert item.source == InboxItem.Source.PAPERLESS
    assert item.external_ref == "paperless:42"
    assert not item.file
    assert item.is_reference
    # El OCR de Paperless vale más que el nuestro: no se vuelve a hacer.
    assert "cobertura amplia" in item.text
    assert item.suggestion.plan["document"]["doc_type"] == "policy"


@pytest.mark.django_db
def test_el_mismo_documento_dos_veces_no_entra_dos_veces(paperless):
    """El repaso periódico repite lo reciente: es su trabajo, no un fallo."""
    listado = json.dumps({"results": [{
        "id": 42, "original_file_name": "poliza.pdf", "content": "Póliza",
    }]}).encode()

    runner = PaperlessRunner()
    with mock.patch.object(runner, "_get_bytes", side_effect=[listado, listado]):
        runner.run(paperless)
        segunda = runner.run(paperless)

    assert segunda.new == 0
    assert InboxItem.objects.count() == 1


@pytest.mark.django_db
def test_el_xml_de_un_cfdi_si_se_baja(paperless):
    """No se lee: se parsea. Está firmado, y esa firma no está en el texto."""
    listado = json.dumps({"results": [{
        "id": 7, "original_file_name": "factura.xml", "content": "texto plano",
    }]}).encode()

    runner = PaperlessRunner()
    with mock.patch.object(runner, "_get_bytes",
                           side_effect=[listado, b"<xml/>"]) as trae:
        runner.run(paperless)

    assert trae.call_count == 2
    item = InboxItem.objects.get()
    assert item.file
    assert item.external_ref == "paperless:7"


@pytest.mark.django_db
def test_paperless_no_crea_documentos_solo(paperless):
    listado = json.dumps({"results": [{"id": 1, "content": "Factura"}]}).encode()
    runner = PaperlessRunner()
    with mock.patch.object(runner, "_get_bytes", side_effect=[listado]):
        runner.run(paperless)

    assert Document.objects.count() == 0       # sigue esperando a una persona


@pytest.mark.django_db
def test_paperless_sin_configurar_avisa_en_vez_de_reventar(scoped):
    vacio = Connector.objects.create(household=scoped, key="paperless", label="Sin datos")
    result = run_connector(vacio)

    assert "Faltan" in result.error
    vacio.refresh_from_db()
    assert vacio.last_error == result.error   # queda constancia


@pytest.mark.django_db
def test_un_paperless_caido_deja_el_error_registrado(paperless):
    runner = PaperlessRunner()
    with mock.patch.object(runner, "_get_bytes", side_effect=OSError("sin ruta al host")):
        result = runner.run(paperless)

    assert "sin ruta" in result.error
    assert InboxItem.objects.count() == 0


# --- Carpeta vigilada -------------------------------------------------------


@pytest.mark.django_db
def test_recoge_lo_que_aparece_en_la_carpeta(scoped, tmp_path):
    (tmp_path / "factura.xml").write_bytes(CFDI_XML)
    (tmp_path / "notas.doc").write_bytes(b"no toca")        # extensión no admitida

    connector = Connector.objects.create(
        household=scoped, key="watchfolder", label="NAS",
        config={"path": str(tmp_path)},
    )
    result = WatchFolderRunner().run(connector)

    assert result.new == 1
    assert InboxItem.objects.get().suggestion.classifier == "core.cfdi"
    # El original se deja donde está mientras no se pida lo contrario.
    assert (tmp_path / "factura.xml").exists()


@pytest.mark.django_db
def test_la_carpeta_no_reprocesa_lo_mismo(scoped, tmp_path):
    (tmp_path / "factura.xml").write_bytes(CFDI_XML)
    connector = Connector.objects.create(
        household=scoped, key="watchfolder", label="NAS",
        config={"path": str(tmp_path)},
    )
    WatchFolderRunner().run(connector)
    segunda = WatchFolderRunner().run(connector)

    assert segunda.fetched == 1 and segunda.new == 0
    assert InboxItem.objects.count() == 1


@pytest.mark.django_db
def test_una_carpeta_que_no_existe_avisa(scoped):
    connector = Connector.objects.create(
        household=scoped, key="watchfolder", label="Fantasma",
        config={"path": "/no/existe"},
    )
    assert "No existe" in WatchFolderRunner().run(connector).error


# --- Correo -----------------------------------------------------------------


@pytest.mark.django_db
def test_sin_lista_blanca_el_buzon_no_acepta_nada(scoped):
    """Un buzón abierto a cualquiera es una vía de entrada para cualquiera."""
    import email.message

    mensaje = email.message.EmailMessage()
    mensaje["From"] = "desconocido@internet.test"

    connector = Connector.objects.create(
        household=scoped, key="imap", label="Buzón", config={"allowed_senders": ""}
    )
    assert ImapRunner()._permitido(mensaje, []) is False
    assert connector.config["allowed_senders"] == ""


@pytest.mark.django_db
def test_acepta_solo_a_los_remitentes_declarados(scoped):
    import email.message

    def de(remitente):
        m = email.message.EmailMessage()
        m["From"] = remitente
        return m

    runner = ImapRunner()
    permitidos = ["facturas@gnp.com.mx", "banco.test"]

    assert runner._permitido(de("facturas@gnp.com.mx"), permitidos)
    assert runner._permitido(de("Avisos <avisos@banco.test>"), permitidos)
    assert not runner._permitido(de("spam@otro.test"), permitidos)
