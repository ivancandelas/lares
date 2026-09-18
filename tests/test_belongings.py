"""Objetos de valor y su ciclo de vida.

La pregunta que se hace la gente no es "¿qué tengo?" sino "¿todavía lo tengo?".
"""

import datetime as dt

import pytest

from lares.core.models import Document, Link, Obligation, Party, Resource
from lares.core.services import checks, obligations
from lares.modules.belongings.models import Belonging

HOY = dt.date.today()


@pytest.fixture
def guitarra(scoped, me):
    return Belonging.objects.create(
        household=scoped, name="Guitarra Martin D-28", kind="belonging",
        category=Belonging.Category.INSTRUMENT, brand="Martin",
        serial_number="2412887", owner=me,
        acquired_on=dt.date(2019, 3, 11), purchase_amount=48000, current_value=52000,
    )


@pytest.fixture
def refri(scoped, me):
    return Belonging.objects.create(
        household=scoped, name="Refrigerador Samsung", kind="belonging",
        category=Belonging.Category.APPLIANCE, owner=me, purchase_amount=28900,
        warranty_until=HOY + dt.timedelta(days=65),
    )


# --- Qué cuenta como objeto de valor ---------------------------------------


@pytest.mark.django_db
def test_joyas_instrumentos_y_arte_siempre_son_de_valor(scoped):
    anillo = Belonging.objects.create(
        household=scoped, name="Anillo", kind="belonging",
        category=Belonging.Category.JEWELRY, purchase_amount=900,
    )
    # Aunque valga poco: lo que importa es que se asegura y duele perderlo.
    assert anillo.is_valuable


@pytest.mark.django_db
def test_lo_barato_y_corriente_no_lo_es(scoped):
    tostadora = Belonging.objects.create(
        household=scoped, name="Tostadora", kind="belonging",
        category=Belonging.Category.APPLIANCE, purchase_amount=800,
    )
    assert not tostadora.is_valuable


# --- Garantías --------------------------------------------------------------


@pytest.mark.django_db
def test_la_garantia_avisa_con_dos_meses_de_margen(scoped, refri):
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.get(source="belongings.warranty")
    assert aviso.due_on == refri.warranty_until
    # Sirve si te acuerdas mientras aún vale, no el día que caduca.
    assert min(aviso.remind_offsets) == -60


@pytest.mark.django_db
def test_una_garantia_ya_vencida_no_genera_ruido(scoped, me):
    Belonging.objects.create(
        household=scoped, name="Viejo", kind="belonging", owner=me,
        warranty_until=HOY - dt.timedelta(days=10),
    )
    obligations.materialize(scoped, HOY)
    assert not Obligation.objects.filter(source="belongings.warranty").exists()


# --- Huecos -----------------------------------------------------------------


@pytest.mark.django_db
def test_avisa_de_un_objeto_de_valor_sin_factura(scoped, guitarra):
    claves = {f.check for f in checks.run_all(scoped)}
    assert "belongings.no_invoice" in claves


@pytest.mark.django_db
def test_deja_de_avisar_cuando_la_factura_esta(scoped, guitarra):
    from django.contrib.contenttypes.models import ContentType

    factura = Document.objects.create(household=scoped, title="Factura guitarra")
    Link.objects.create(
        household=scoped,
        source_type=ContentType.objects.get_for_model(Document), source_id=factura.pk,
        role="documents",
        target_type=ContentType.objects.get_for_model(Belonging), target_id=guitarra.pk,
    )
    claves = {f.check for f in checks.run_all(scoped)}
    assert "belongings.no_invoice" not in claves


# --- Ciclo de vida ----------------------------------------------------------


@pytest.mark.django_db
def test_vender_algo_no_lo_borra(scoped, guitarra):
    andrea = Party.objects.create(household=scoped, name="Andrea")
    guitarra.dispose(Belonging.Disposal.SOLD, on_date=dt.date(2026, 2, 20),
                     to=andrea, amount=39000)

    guitarra.refresh_from_db()
    assert guitarra.status == Belonging.Status.DISPOSED
    assert Belonging.objects.filter(pk=guitarra.pk).exists()      # sigue ahí
    assert "Vendido" in guitarra.disposal_line
    assert "Andrea" in guitarra.disposal_line


@pytest.mark.django_db
def test_lo_vendido_deja_de_contar_en_el_patrimonio(scoped, guitarra, refri):
    activos = Resource.objects.filter(status=Resource.Status.ACTIVE)
    antes = sum(r.current_value or r.purchase_amount or 0 for r in activos)

    guitarra.dispose(Belonging.Disposal.SOLD, amount=39000)

    activos = Resource.objects.filter(status=Resource.Status.ACTIVE)
    despues = sum(r.current_value or r.purchase_amount or 0 for r in activos)
    assert despues == antes - 52000


@pytest.mark.django_db
def test_lo_perdido_se_registra_igual_que_lo_vendido(scoped, guitarra):
    guitarra.dispose(Belonging.Disposal.LOST, note="No aparece desde la mudanza")

    guitarra.refresh_from_db()
    assert guitarra.disposal_reason == Belonging.Disposal.LOST
    assert guitarra.disposal_amount is None
    assert "Perdido" in guitarra.disposal_line


@pytest.mark.django_db
def test_lo_dado_de_baja_no_genera_obligaciones(scoped, refri):
    obligations.materialize(scoped, HOY)
    assert Obligation.objects.filter(source="belongings.warranty").count() == 1

    refri.dispose(Belonging.Disposal.SCRAPPED)
    Obligation.objects.all().delete()
    obligations.materialize(scoped, HOY)

    assert not Obligation.objects.filter(source="belongings.warranty").exists()


@pytest.mark.django_db
def test_avisa_de_lo_que_no_compruebas_hace_un_ano(scoped, guitarra):
    Resource.objects.filter(pk=guitarra.pk).update(
        verified_on=HOY - dt.timedelta(days=400)
    )
    claves = {f.check for f in checks.run_all(scoped)}
    assert "belongings.stale" in claves


@pytest.mark.django_db
def test_comprobarlo_calla_el_aviso(scoped, guitarra):
    Resource.objects.filter(pk=guitarra.pk).update(verified_on=HOY)
    claves = {f.check for f in checks.run_all(scoped)}
    assert "belongings.stale" not in claves


# --- Pantallas --------------------------------------------------------------


@pytest.fixture
def sesion(client, django_user_model, household):
    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_dar_de_baja_desde_la_ficha(sesion, household, scoped, guitarra):
    respuesta = sesion.post(f"/r/{guitarra.pk}/baja/", {
        "disposal_reason": "sold", "disposed_on": "2026-02-20",
        "disposal_amount": "39000",
    })
    assert respuesta.status_code == 302

    guitarra.refresh_from_db()
    assert guitarra.status == Resource.Status.DISPOSED
    assert guitarra.disposal_amount == 39000


@pytest.mark.django_db
def test_una_baja_puesta_por_error_se_deshace(sesion, household, scoped, guitarra):
    guitarra.dispose(Belonging.Disposal.LOST)
    sesion.post(f"/r/{guitarra.pk}/recuperar/")

    guitarra.refresh_from_db()
    assert guitarra.status == Resource.Status.ACTIVE
    assert guitarra.disposal_reason == ""


@pytest.mark.django_db
def test_confirmar_que_sigues_teniendolo(sesion, household, scoped, guitarra):
    sesion.post(f"/r/{guitarra.pk}/comprobar/")

    guitarra.refresh_from_db()
    assert guitarra.verified_on == HOY


@pytest.mark.django_db
def test_el_patrimonio_separa_lo_que_ya_no_tienes(sesion, household, scoped,
                                                  guitarra, refri):
    guitarra.dispose(Belonging.Disposal.SOLD, amount=39000)
    contenido = sesion.get("/patrimonio/").content.decode()

    assert "Ya no los tienes" in contenido
    assert "Refrigerador Samsung" in contenido
