"""La integración con Paperless-ngx, de punta a punta.

La regla del producto estaba escrita desde F2 y el código hacía lo contrario:
bajaba el PDF a su propio almacén y tiraba la referencia al confirmar. Estas
pruebas fijan las tres cosas que la hacen cierta:

    se referencia          el binario no se copia; se guarda `paperless:<id>`
    la referencia viaja    del item de bandeja al documento, al confirmar
    se materializa         solo cuando el archivo tiene que salir de aquí
"""

import io
import json
import zipfile
from unittest import mock

import pytest

from lares.core.models import ApiKey, Connector, Document, InboxItem
from lares.core.services import ingest, paperless


@pytest.fixture
def conector(scoped):
    c = Connector.objects.create(
        household=scoped, key="paperless", label="Paperless de casa",
        config={"base_url": "https://paperless.test", "page_size": 10},
    )
    c.secret = "token"
    c.save()
    return c


@pytest.fixture
def referenciado(scoped, conector):
    item, _ = ingest.receive_reference(
        scoped, ref="paperless:42", name="poliza_mazda.pdf",
        text="Póliza de cobertura amplia",
    )
    return item


# --- La referencia viaja hasta el documento ---------------------------------


@pytest.mark.django_db
def test_al_confirmar_el_documento_se_queda_con_la_referencia(scoped, referenciado):
    """Se perdía justo al confirmar, que es cuando empieza a valer."""
    documento = Document.objects.create(household=scoped, title="Póliza del Mazda")

    with mock.patch.object(paperless, "write_back", return_value=False):
        ingest.apply(referenciado, documento)

    documento.refresh_from_db()
    assert documento.external_ref == "paperless:42"
    assert not documento.file          # el archivo sigue viviendo fuera


@pytest.mark.django_db
def test_el_enlace_para_abrirlo_en_paperless_se_arma_solo(scoped, conector,
                                                          referenciado):
    documento = Document.objects.create(household=scoped, title="Póliza",
                                        external_ref="paperless:42")

    [anotado] = paperless.annotate_links(scoped, [documento])

    assert anotado.external_url == "https://paperless.test/documents/42/details"


@pytest.mark.django_db
def test_sin_conector_no_se_inventa_un_enlace(scoped):
    documento = Document.objects.create(household=scoped, title="Póliza",
                                        external_ref="paperless:42")

    [anotado] = paperless.annotate_links(scoped, [documento])

    assert anotado.external_url == ""


# --- Verlo sin repartir el token de Paperless -------------------------------


@pytest.mark.django_db
def test_el_archivo_se_sirve_por_lares_y_no_redirigiendo(scoped, conector,
                                                         sesion_admin):
    """Redirigir obligaría a exponer Paperless y a repartir su token."""
    documento = Document.objects.create(household=scoped, title="Póliza",
                                        external_ref="paperless:42")

    with mock.patch.object(paperless, "fetch",
                           return_value=(b"%PDF-1.4 hola", "application/pdf")):
        respuesta = sesion_admin.get(f"/d/{documento.pk}/ver/")

    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/pdf"
    assert b"hola" in respuesta.content


@pytest.mark.django_db
def test_si_paperless_calla_lo_dice_y_no_revienta(scoped, conector, sesion_admin):
    """No está roto Lares: está callado Paperless, y son cosas distintas."""
    documento = Document.objects.create(household=scoped, title="Póliza",
                                        external_ref="paperless:42")

    with mock.patch.object(paperless, "fetch",
                           side_effect=paperless.Inalcanzable("sin respuesta")):
        respuesta = sesion_admin.get(f"/d/{documento.pk}/ver/")

    assert respuesta.status_code == 502
    assert "no responde" in respuesta.content.decode()


@pytest.mark.django_db
def test_lo_referenciado_se_puede_mirar_antes_de_confirmarlo(scoped, conector,
                                                             referenciado,
                                                             sesion_admin):
    with mock.patch.object(paperless, "fetch",
                           return_value=(b"%PDF-1.4", "application/pdf")):
        respuesta = sesion_admin.get(f"/bandeja/{referenciado.pk}/archivo/")

    assert respuesta.status_code == 200
    pantalla = sesion_admin.get(f"/bandeja/{referenciado.pk}/")
    assert "está en Paperless" in pantalla.content.decode()


# --- El webhook -------------------------------------------------------------


@pytest.fixture
def llave(scoped):
    key, token = ApiKey.issue(scoped, name="paperless")
    return token


@pytest.mark.django_db
def test_el_webhook_mete_el_documento_en_la_bandeja(scoped, conector, llave,
                                                    client):
    documento = {"id": 99, "original_file_name": "predial.pdf",
                 "content": "Predial 2026"}

    with mock.patch.object(paperless, "metadata", return_value=documento):
        respuesta = client.post("/api/v1/inbox/paperless",
                                data=json.dumps({"doc_pk": 99}),
                                content_type="application/json",
                                HTTP_X_LARES_KEY=llave)

    assert respuesta.status_code == 201
    item = InboxItem.all_objects.get()
    assert item.external_ref == "paperless:99"
    assert "Predial" in item.text


@pytest.mark.django_db
def test_un_aviso_repetido_no_crea_una_segunda_entrada(scoped, conector, llave,
                                                       client):
    """Los webhooks se repiten. Siempre."""
    documento = {"id": 99, "original_file_name": "predial.pdf", "content": "x"}

    with mock.patch.object(paperless, "metadata", return_value=documento):
        for _ in range(3):
            respuesta = client.post("/api/v1/inbox/paperless",
                                    data=json.dumps({"doc_pk": 99}),
                                    content_type="application/json",
                                    HTTP_X_LARES_KEY=llave)

    assert respuesta.status_code == 200          # ya estaba
    assert InboxItem.all_objects.count() == 1


@pytest.mark.django_db
def test_el_webhook_sin_llave_no_entra(scoped, client):
    respuesta = client.post("/api/v1/inbox/paperless",
                            data=json.dumps({"doc_pk": 1}),
                            content_type="application/json")

    assert respuesta.status_code == 401


@pytest.mark.django_db
def test_si_paperless_no_contesta_el_webhook_lo_dice(scoped, conector, llave,
                                                     client):
    with mock.patch.object(paperless, "metadata",
                           side_effect=paperless.Inalcanzable("timeout")):
        respuesta = client.post("/api/v1/inbox/paperless",
                                data=json.dumps({"doc_pk": 5}),
                                content_type="application/json",
                                HTTP_X_LARES_KEY=llave)

    assert respuesta.status_code == 502


# --- Materializar: cuando el archivo tiene que salir de aquí ----------------


@pytest.mark.django_db
def test_el_paquete_de_sucesion_se_lleva_el_pdf_de_paperless(scoped, conector,
                                                             client):
    """Un paquete que solo funciona con el servidor de casa encendido no sirve."""
    from lares.core.models import EmergencyContact
    from lares.core.services import succession

    Document.objects.create(household=scoped, title="Escritura de la casa",
                            external_ref="paperless:7")
    contacto = EmergencyContact.objects.create(household=scoped, name="Ana",
                                               email="ana@x.mx")
    succession.release(contacto)

    with mock.patch.object(paperless, "fetch",
                           return_value=(b"%PDF-1.4 escritura", "application/pdf")):
        respuesta = client.get(f"/sucesion/{contacto.token}/paquete.zip")

    contenido = b"".join(respuesta.streaming_content)
    with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
        nombres = zf.namelist()
        assert "documentos/Escritura de la casa.pdf" in nombres
        assert b"escritura" in zf.read("documentos/Escritura de la casa.pdf")


@pytest.mark.django_db
def test_la_exportacion_completa_tambien_se_lo_lleva(scoped, conector, tmp_path):
    """Es «la prueba de que los datos son del usuario»: sin el PDF no lo es."""
    from lares.core.services import portability

    Document.objects.create(household=scoped, title="Escritura",
                            external_ref="paperless:7")
    destino = tmp_path / "export.zip"

    with mock.patch.object(paperless, "fetch",
                           return_value=(b"%PDF-1.4 escritura", "application/pdf")):
        portability.export_household(scoped, destino)

    with zipfile.ZipFile(destino) as zf:
        archivos = [n for n in zf.namelist() if n.startswith("files/")]
        assert archivos
        assert b"escritura" in zf.read(archivos[0])


@pytest.mark.django_db
def test_si_paperless_calla_el_paquete_sale_igual_pero_sin_ese_archivo(
        scoped, conector, client):
    """Un paquete incompleto vale más que un paquete que no se genera."""
    from lares.core.models import EmergencyContact
    from lares.core.services import succession

    Document.objects.create(household=scoped, title="Escritura",
                            external_ref="paperless:7")
    contacto = EmergencyContact.objects.create(household=scoped, name="Ana",
                                               email="ana@x.mx")
    succession.release(contacto)

    with mock.patch.object(paperless, "fetch",
                           side_effect=paperless.Inalcanzable("caído")):
        respuesta = client.get(f"/sucesion/{contacto.token}/paquete.zip")

    assert respuesta.status_code == 200
    contenido = b"".join(respuesta.streaming_content)
    with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
        assert "paquete.json" in zf.namelist()
        assert not [n for n in zf.namelist() if n.startswith("documentos/")]


# --- La vuelta --------------------------------------------------------------


@pytest.mark.django_db
def test_la_vuelta_solo_se_escribe_si_se_pidio(scoped, conector):
    """Escribir en Paperless sin que nadie lo pida es tocar datos de otro."""
    assert paperless.write_back(scoped, "paperless:42", "https://lares/d/1") is False

    conector.config["write_back"] = True
    conector.save(update_fields=["config"])

    with mock.patch.object(paperless, "_custom_field_id", return_value=3), \
         mock.patch("urllib.request.urlopen") as abrir:
        abrir.return_value.__enter__ = lambda s: s
        abrir.return_value.__exit__ = lambda *a: None
        assert paperless.write_back(scoped, "paperless:42", "https://lares/d/1")


@pytest.mark.django_db
def test_que_falle_la_vuelta_no_impide_registrar(scoped, conector, referenciado):
    documento = Document.objects.create(household=scoped, title="Póliza")

    with mock.patch.object(paperless, "write_back",
                           side_effect=RuntimeError("Paperless dijo que no")):
        ingest.apply(referenciado, documento)

    referenciado.refresh_from_db()
    assert referenciado.status == InboxItem.Status.APPLIED
