"""Ver un archivo sin descargarlo, y sin que se filtre.

Dos fallos reales que cubren estas pruebas:

  1. Django trae `X-Frame-Options: DENY`, que impide incrustar hasta los
     archivos propios. El visor se quedaba en blanco sin ningún error visible.
  2. Servir desde /media/ no comprueba nada: cualquiera con sesión podía leer
     el archivo de otra casa conociendo la ruta.
"""

import pytest
from django.core.files.base import ContentFile

from lares.core.models import Document, Household, InboxItem
from lares.core.scoping import use_household
from lares.core.services import ingest

PDF = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


@pytest.fixture
def item(scoped):
    from django.core.files.uploadedfile import SimpleUploadedFile

    archivo = SimpleUploadedFile("poliza.pdf", PDF, content_type="application/pdf")
    entrada, _ = ingest.receive(scoped, archivo)
    return entrada


# --- Se puede incrustar -----------------------------------------------------


@pytest.mark.django_db
def test_el_archivo_se_puede_incrustar_en_un_marco(sesion_admin, item):
    respuesta = sesion_admin.get(f"/bandeja/{item.pk}/archivo/")

    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/pdf"
    # DENY dejaba el visor en blanco sin decir por qué.
    assert respuesta.get("X-Frame-Options") != "DENY"


@pytest.mark.django_db
def test_ninguna_pantalla_se_sirve_con_deny(sesion_admin, household):
    """Si vuelve DENY, todos los visores dejan de funcionar a la vez."""
    assert sesion_admin.get("/").get("X-Frame-Options") != "DENY"


@pytest.mark.django_db
def test_la_revision_incrusta_el_pdf(sesion_admin, household, scoped, item):
    contenido = sesion_admin.get(f"/bandeja/{item.pk}/").content.decode()

    assert "<iframe" in contenido
    assert f"/bandeja/{item.pk}/archivo/" in contenido
    # Nunca la URL de medios: esa no comprueba el hogar.
    assert "/media/" not in contenido


# --- No se filtra -----------------------------------------------------------


@pytest.mark.django_db
def test_el_archivo_de_otra_casa_no_se_abre(sesion_admin, scoped):
    ajena = Household.objects.create(name="Zeta ajena", slug="zeta")
    with use_household(ajena):
        doc = Document.objects.create(household=ajena, title="Escritura ajena")
        doc.file.save("secreto.pdf", ContentFile(PDF), save=True)
        entrada = InboxItem.objects.create(
            household=ajena, checksum="x" * 64, original_name="ajeno.pdf",
        )
        entrada.file.save("ajeno.pdf", ContentFile(PDF), save=True)

    assert sesion_admin.get(f"/d/{doc.pk}/ver/").status_code == 404
    assert sesion_admin.get(f"/bandeja/{entrada.pk}/archivo/").status_code == 404


@pytest.mark.django_db
def test_sin_sesion_no_se_ve_nada(client, item):
    respuesta = client.get(f"/bandeja/{item.pk}/archivo/")
    assert respuesta.status_code == 302
    assert "/entrar/" in respuesta["Location"]


# --- Qué se puede previsualizar --------------------------------------------


@pytest.mark.django_db
def test_reconoce_lo_que_el_navegador_sabe_mostrar(scoped):
    from lares.core.views import preview_kind

    pdf = Document.objects.create(household=scoped, title="PDF",
                                  mime_type="application/pdf")
    pdf.file.save("a.pdf", ContentFile(PDF), save=True)
    foto = Document.objects.create(household=scoped, title="Foto",
                                   mime_type="image/jpeg")
    foto.file.save("a.jpg", ContentFile(b"xx"), save=True)
    hoja = Document.objects.create(household=scoped, title="Hoja",
                                   mime_type="application/vnd.ms-excel")
    hoja.file.save("a.xls", ContentFile(b"xx"), save=True)

    assert preview_kind(pdf) == "pdf"
    assert preview_kind(foto) == "image"
    assert preview_kind(hoja) == ""          # se ofrece descargar, no se finge
