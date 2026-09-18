"""La bandeja: el cuello de botella real del producto.

Lo que se prueba es lo que puede romper la confianza: que nada se cree sin que
una persona lo confirme, que subir dos veces lo mismo no duplique nada, y que
el crudo se conserve para poder reprocesarlo cuando el clasificador mejore.
"""

import pathlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from lares.core.models import Document, InboxItem, Obligation, Party, Suggestion
from lares.core.services import cfdi, ingest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CFDI_XML = (FIXTURES / "cfdi_ejemplo.xml").read_bytes()


def _subir(nombre, contenido, tipo="application/xml"):
    return SimpleUploadedFile(nombre, contenido, content_type=tipo)


# --- Lectura del CFDI -------------------------------------------------------


def test_lee_un_cfdi_real():
    factura = cfdi.parse(CFDI_XML)

    assert factura.issuer_tax_id == "AAA010101AAA"
    assert factura.issuer_name == "Servicio Automotriz del Valle SA de CV"
    assert factura.total == "4750.00"
    assert factura.currency == "MXN"
    assert factura.uuid == "A1B2C3D4-5E6F-4071-8A9B-0C1D2E3F4A5B"
    assert str(factura.issued_at) == "2026-09-12"
    assert [c["description"] for c in factura.concepts] == [
        "Servicio mayor 40,000 km", "Aceite sintético 5W30",
    ]


def test_un_xml_cualquiera_no_es_un_cfdi():
    assert cfdi.parse(b"<algo><otra/></algo>") is None
    assert cfdi.parse(b"esto no es xml") is None


# --- Bandeja ----------------------------------------------------------------


@pytest.mark.django_db
def test_un_cfdi_entra_reconocido_y_con_los_datos_puestos(scoped):
    item, nuevo = ingest.receive(scoped, _subir("factura.xml", CFDI_XML))

    assert nuevo
    propuesta = item.suggestion
    assert propuesta.classifier == "core.cfdi"
    assert propuesta.confidence == 0.99          # está firmado: no se adivina
    assert propuesta.plan["document"]["amount"] == "4750.00"
    assert propuesta.plan["party"]["tax_id"] == "AAA010101AAA"


@pytest.mark.django_db
def test_reconocer_no_es_registrar(scoped):
    """Lo más importante de todo el módulo: el clasificador no escribe nada."""
    ingest.receive(scoped, _subir("factura.xml", CFDI_XML))

    assert Document.objects.count() == 0
    assert Party.objects.count() == 0
    # Varios clasificadores pueden opinar sobre el mismo archivo; ninguno escribe.
    assert Suggestion.objects.exists()


@pytest.mark.django_db
def test_gana_la_propuesta_con_mas_certeza(scoped):
    """Un XML del SAT también dispara las pistas por palabra clave.

    La ficha tiene que quedarse con la lectura firmada, no con la corazonada.
    """
    item, _ = ingest.receive(scoped, _subir("factura.xml", CFDI_XML))

    assert Suggestion.objects.filter(item=item).count() > 1
    assert item.suggestion.classifier == "core.cfdi"


@pytest.mark.django_db
def test_subir_dos_veces_lo_mismo_no_duplica(scoped):
    primero, nuevo1 = ingest.receive(scoped, _subir("factura.xml", CFDI_XML))
    segundo, nuevo2 = ingest.receive(scoped, _subir("otro-nombre.xml", CFDI_XML))

    assert nuevo1 and not nuevo2
    assert primero.pk == segundo.pk
    assert InboxItem.objects.count() == 1


@pytest.mark.django_db
def test_al_confirmar_se_crea_el_documento_y_el_proveedor(scoped):
    item, _ = ingest.receive(scoped, _subir("factura.xml", CFDI_XML))
    datos = ingest.initial_document_data(item)

    documento = Document.objects.create(
        household=scoped, title=datos["title"], doc_type=datos["doc_type"],
        amount=datos["amount"], currency=datos["currency"],
    )
    ingest.apply(item, documento)

    item.refresh_from_db()
    assert item.status == InboxItem.Status.APPLIED
    assert item.applied_document_id == documento.pk
    # El RFC del emisor se convierte en un proveedor identificable.
    assert Party.objects.get(tax_id="AAA010101AAA").kind == Party.Kind.ORGANIZATION


@pytest.mark.django_db
def test_descartar_conserva_el_archivo_para_reprocesarlo(scoped):
    item, _ = ingest.receive(scoped, _subir("factura.xml", CFDI_XML))
    ingest.discard(item)

    item.refresh_from_db()
    assert item.status == InboxItem.Status.DISCARDED
    assert item.file                       # el crudo sigue ahí
    assert item.checksum


@pytest.mark.django_db
def test_reconoce_por_pistas_lo_que_no_es_un_cfdi(scoped):
    item, _ = ingest.receive(
        scoped,
        _subir("poliza_seguro_mazda.txt", "Póliza de cobertura amplia".encode(), "text/plain"),
    )
    assert item.suggestion.plan["document"]["doc_type"] == "policy"
    assert item.suggestion.confidence < 0.9   # es una pista, no una certeza


@pytest.mark.django_db
def test_lo_irreconocible_entra_igual_y_espera_a_la_persona(scoped):
    item, _ = ingest.receive(scoped, _subir("IMG_4471.txt", b"xyz", "text/plain"))

    assert item.suggestion is None
    assert item.status == InboxItem.Status.NEW
    assert ingest.initial_document_data(item) == {"title": "IMG_4471"}


# --- Pantallas --------------------------------------------------------------


@pytest.fixture
def sesion(client, django_user_model, household):
    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_subir_y_confirmar_desde_la_pantalla(sesion, household):
    from lares.core.scoping import use_household

    sesion.post("/bandeja/", {"files": _subir("factura.xml", CFDI_XML)})
    with use_household(household):
        item = InboxItem.objects.get()

    respuesta = sesion.get(f"/bandeja/{item.pk}/")
    assert respuesta.status_code == 200
    assert b"Servicio Automotriz" in respuesta.content

    sesion.post(f"/bandeja/{item.pk}/", {
        "title": "Servicio del Mazda", "doc_type": "invoice",
        "amount": "4750.00", "currency": "MXN", "confidentiality": "normal",
        "expires_on": "", "issued_on": "2026-09-12",
    })
    with use_household(household):
        assert Document.objects.get().title == "Servicio del Mazda"
        item.refresh_from_db()
        assert item.status == InboxItem.Status.APPLIED


@pytest.mark.django_db
def test_confirmar_un_documento_con_vencimiento_crea_el_aviso(sesion, household):
    from lares.core.scoping import use_household

    sesion.post("/bandeja/", {
        "files": _subir("pasaporte.txt", "Pasaporte".encode(), "text/plain"),
    })
    with use_household(household):
        item = InboxItem.objects.get()

    sesion.post(f"/bandeja/{item.pk}/", {
        "title": "Pasaporte", "doc_type": "passport",
        "expires_on": "2027-05-16", "confidentiality": "normal",
    })
    with use_household(household):
        assert Obligation.objects.filter(source="core.document_expiry").exists()


@pytest.mark.django_db
def test_el_manifiesto_declara_el_destino_de_compartir(client):
    datos = client.get("/manifest.webmanifest").json()

    assert datos["share_target"]["action"] == "/bandeja/compartir/"
    assert datos["share_target"]["method"] == "POST"


@pytest.mark.django_db
def test_subir_funciona_aunque_la_cola_este_caida(scoped, monkeypatch):
    """Si Redis no está, se pierde el webhook, no la factura."""
    from lares.core import tasks

    def cola_caida(*args, **kwargs):
        raise OSError("no hay ruta al broker")

    monkeypatch.setattr(tasks.dispatch_webhooks, "delay", cola_caida)

    item, nuevo = ingest.receive(scoped, _subir("factura.xml", CFDI_XML))
    assert nuevo
    assert InboxItem.objects.count() == 1
