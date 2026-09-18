"""Contactos: etiquetas, vCard y enlaces compartidos.

La prueba de que un directorio sirve no es que guarde teléfonos, sino que se
pueda sacar de aquí: en el formato de todos, y compartido con quien lo necesita.
"""

import datetime as dt

import pytest

from lares.core.models import ContactPoint, Obligation, Party, Share, Tag
from lares.core.models.tagging import set_tags, tagged, tags_of
from lares.core.services import obligations, vcard

HOY = dt.date.today()


@pytest.fixture
def familia(scoped):
    gente = {}
    for nombre, cumple in (("Mariana", dt.date(1988, 6, 14)),
                           ("Diego", dt.date(2011, 3, 2))):
        p = Party.objects.create(household=scoped, name=nombre, birth_date=cumple)
        ContactPoint.objects.create(household=scoped, party=p,
                                    channel=ContactPoint.Channel.PHONE,
                                    value="33 1234 5678", label="móvil")
        set_tags(p, ["familia", "casa"])
        gente[nombre] = p
    return gente


# --- Etiquetas --------------------------------------------------------------


@pytest.mark.django_db
def test_las_etiquetas_se_crean_solas_al_usarlas(scoped):
    """Nadie debería mantener una lista de categorías antes de guardar a alguien."""
    p = Party.objects.create(household=scoped, name="Luis")
    set_tags(p, ["familia", "  amigos  "])

    assert {t.name for t in tags_of(p)} == {"familia", "amigos"}
    assert Tag.objects.count() == 2


@pytest.mark.django_db
def test_volver_a_etiquetar_deja_exactamente_lo_indicado(scoped):
    p = Party.objects.create(household=scoped, name="Luis")
    set_tags(p, ["familia", "trabajo"])
    set_tags(p, ["familia"])

    assert [t.name for t in tags_of(p)] == ["familia"]


@pytest.mark.django_db
def test_una_etiqueta_agrupa_a_toda_su_gente(scoped, familia):
    fam = Tag.objects.get(slug="familia")
    assert {p.name for p in tagged(fam, Party)} == {"Mariana", "Diego"}


@pytest.mark.django_db
def test_las_etiquetas_no_se_mezclan_entre_hogares(scoped):
    from lares.core.models import Household
    from lares.core.scoping import use_household

    p = Party.objects.create(household=scoped, name="Luis")
    set_tags(p, ["familia"])

    otro = Household.objects.create(name="Otra", slug="otra")
    with use_household(otro):
        ajeno = Party.objects.create(household=otro, name="Ajeno")
        set_tags(ajeno, ["familia"])
        # Mismo nombre, etiqueta distinta: cada casa tiene la suya.
        assert Tag.objects.count() == 1

    assert Tag.objects.count() == 1


# --- vCard ------------------------------------------------------------------


@pytest.mark.django_db
def test_exporta_en_el_formato_que_todos_entienden(scoped, familia):
    salida = vcard.export([familia["Diego"]])

    assert salida.startswith("BEGIN:VCARD\r\n")
    assert "VERSION:4.0" in salida
    assert salida.rstrip().endswith("END:VCARD")
    assert "FN:Diego" in salida
    assert "TEL" in salida and "33 1234 5678" in salida
    assert "BDAY:20110302" in salida


@pytest.mark.django_db
def test_las_etiquetas_viajan_en_la_vcard(scoped, familia):
    """Así el teléfono de quien lo recibe también los agrupa."""
    salida = vcard.export([familia["Diego"]])
    assert "CATEGORIES:familia" in salida


@pytest.mark.django_db
def test_se_exporta_una_etiqueta_entera(scoped, familia):
    fam = Tag.objects.get(slug="familia")
    salida = vcard.export(tagged(fam, Party))

    assert salida.count("BEGIN:VCARD") == 2


@pytest.mark.django_db
def test_los_puntos_y_coma_se_escapan(scoped):
    p = Party.objects.create(household=scoped, name="Pérez; Juan, hijo")
    assert r"FN:Pérez\; Juan\, hijo" in vcard.export([p])


@pytest.mark.django_db
def test_una_organizacion_se_marca_como_tal(scoped):
    p = Party.objects.create(household=scoped, name="GNP",
                             kind=Party.Kind.ORGANIZATION)
    salida = vcard.export([p])

    assert "KIND:org" in salida
    assert "ORG:GNP" in salida


# --- Cumpleaños -------------------------------------------------------------


@pytest.mark.django_db
def test_los_cumpleanos_entran_por_el_mismo_motor(scoped, familia):
    """Así aparecen en el tablero y en el calendario sin escribir nada aparte."""
    obligations.materialize(scoped, HOY)

    cumples = Obligation.objects.filter(source="core.birthday")
    assert cumples.count() >= 2
    assert any("Mariana" in o.title for o in cumples)


@pytest.mark.django_db
def test_el_cumpleanos_lleva_la_edad(scoped, familia):
    obligations.materialize(scoped, HOY)
    aviso = Obligation.objects.filter(title__contains="Diego").first()
    assert aviso.extra["age"] > 10


@pytest.mark.django_db
def test_quien_no_tiene_fecha_no_genera_nada(scoped):
    Party.objects.create(household=scoped, name="Sin fecha")
    obligations.materialize(scoped, HOY)
    assert not Obligation.objects.filter(source="core.birthday").exists()


@pytest.mark.django_db
def test_los_cumpleanos_salen_en_el_calendario(scoped, familia):
    from lares.core.services import calendar as cal

    obligations.materialize(scoped, HOY)
    assert "Cumpleaños de Mariana" in cal.feed(scoped)


# --- Compartir --------------------------------------------------------------


@pytest.fixture
def enlace(scoped, familia):
    return Share.objects.create(
        household=scoped, kind=Share.Kind.CONTACTS, label="Familia para Mariana",
        target="familia", note="Mariana",
        expires_on=HOY + dt.timedelta(days=90),
    )


@pytest.mark.django_db
def test_el_enlace_abre_sin_sesion_y_solo_muestra_lo_compartido(client, enlace,
                                                                familia, scoped):
    otro = Party.objects.create(household=scoped, name="Secreto del trabajo")
    set_tags(otro, ["trabajo"])

    contenido = client.get(f"/c/{enlace.token}/").content.decode()

    assert "Mariana" in contenido
    assert "Secreto del trabajo" not in contenido


@pytest.mark.django_db
def test_quien_lo_recibe_puede_guardarlo_en_su_telefono(client, enlace):
    respuesta = client.get(f"/c/{enlace.token}.vcf")

    assert respuesta.status_code == 200
    assert respuesta["Content-Type"].startswith("text/vcard")
    assert b"BEGIN:VCARD" in respuesta.content


@pytest.mark.django_db
def test_se_cuenta_quien_lo_abre(client, enlace):
    """Saber si alguien entró es la diferencia entre compartir y perder de vista."""
    client.get(f"/c/{enlace.token}/")
    client.get(f"/c/{enlace.token}/")

    enlace.refresh_from_db()
    assert enlace.hits == 2
    assert enlace.last_seen_at is not None


@pytest.mark.django_db
def test_revocar_lo_apaga_al_instante(client, enlace):
    from django.utils import timezone

    enlace.revoked_at = timezone.now()
    enlace.save()

    assert client.get(f"/c/{enlace.token}/").status_code == 404
    assert client.get(f"/c/{enlace.token}.vcf").status_code == 404


@pytest.mark.django_db
def test_un_enlace_caducado_deja_de_abrir(client, scoped, familia):
    caducado = Share.objects.create(
        household=scoped, label="Viejo", target="familia",
        expires_on=HOY - dt.timedelta(days=1),
    )
    assert not caducado.is_live
    assert client.get(f"/c/{caducado.token}/").status_code == 404


@pytest.mark.django_db
def test_un_token_inventado_no_abre_nada(client, enlace):
    assert client.get("/c/loquesea/").status_code == 404


@pytest.mark.django_db
def test_la_pagina_dice_que_tienes_compartido(sesion_admin, scoped, enlace):
    contenido = sesion_admin.get("/compartido/").content.decode()

    assert "Familia para Mariana" in contenido
    assert "nadie lo ha abierto" in contenido
