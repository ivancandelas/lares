"""Formularios: que se pueda llenar el sistema sin abrir una consola.

Lo que se prueba aquí no es que Django guarde un modelo, sino las tres cosas
que de verdad pueden romperse: que un módulo tenga pantallas sin escribirlas,
que un desplegable no ofrezca datos de otro hogar, y que registrar un gasto
escriba partida doble sin que el usuario se entere.
"""

import datetime as dt

import pytest

from lares.core.forms import DocumentForm, ExpenseForm, ObligationRuleForm
from lares.core.models import Account, Document, Entry, Link, Obligation, Party
from lares.core.registry import registry
from lares.modules.vehicles.models import Vehicle


@pytest.fixture
def usuario(db, django_user_model):
    return django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )


@pytest.fixture
def sesion(client, usuario, household):
    client.force_login(usuario)
    return client


def test_los_modulos_registran_su_formulario():
    """El núcleo no escribe un CRUD por módulo: cada uno aporta el suyo."""
    assert "vehicle" in registry.resource_forms
    assert "credit_card" in registry.resource_forms


@pytest.mark.django_db
def test_dar_de_alta_un_coche_genera_sus_vencimientos(sesion, household):
    response = sesion.post("/nuevo/vehicle/", {
        "name": "Honda CR-V", "make": "Honda", "model": "CR-V", "year": "2024",
        "plates": "JAB7789", "odometer_km": "12500", "avg_km_per_month": "800",
        "service_interval_km": "10000", "last_service_km": "10000",
        "currency": "MXN", "status": "active",
    })
    assert response.status_code == 302

    from lares.core.scoping import use_household
    with use_household(household):
        coche = Vehicle.objects.get()
        assert coche.kind == "vehicle"          # lo pone el formulario, no el usuario
        # Del dato "placas" salen solas la verificación y el refrendo.
        fuentes = set(Obligation.objects.values_list("source", flat=True))
        assert "vehicles.verificacion" in fuentes
        assert "vehicles.refrendo" in fuentes


@pytest.mark.django_db
def test_un_desplegable_no_ofrece_datos_de_otro_hogar(scoped):
    from lares.core.models import Household
    from lares.core.scoping import use_household

    ajeno = Household.objects.create(name="Casa ajena", slug="ajena")
    with use_household(ajeno):
        Party.objects.create(household=ajeno, name="Contacto ajeno")
    mio = Party.objects.create(household=scoped, name="Mi contacto")

    form = DocumentForm(household=scoped)
    ofrecidos = list(form.fields["issuer"].queryset)
    assert ofrecidos == [mio]


@pytest.mark.django_db
def test_un_documento_se_puede_atar_a_una_cosa_al_subirlo(scoped, me):
    coche = Vehicle.objects.create(
        household=scoped, name="Mazda", kind="vehicle", plates="JGT1234", owner=me
    )
    form = DocumentForm(
        {"title": "Factura del Mazda", "doc_type": "invoice", "attach_to": coche.pk,
         "confidentiality": "normal"},
        household=scoped,
    )
    assert form.is_valid(), form.errors
    doc = form.save()

    enlace = Link.objects.get(role="documents")
    assert enlace.source_id == doc.pk
    assert enlace.target_id == coche.pk


@pytest.mark.django_db
def test_registrar_un_gasto_escribe_partida_doble(scoped):
    tarjeta = Account.objects.create(
        household=scoped, name="Tarjeta", type=Account.Type.LIABILITY
    )
    gasolina = Account.objects.create(
        household=scoped, name="Gasolina", type=Account.Type.EXPENSE
    )
    form = ExpenseForm({
        "date": "2026-09-18", "description": "Gasolina", "amount": "980",
        "paid_from": tarjeta.pk, "category": gasolina.pk,
    }, household=scoped)
    assert form.is_valid(), form.errors
    entry = form.save()

    # El usuario rellenó tres campos; por dentro son dos apuntes que cuadran.
    assert entry.postings.count() == 2
    assert entry.is_balanced
    assert tarjeta.balance == 980


@pytest.mark.django_db
def test_un_gasto_se_puede_atribuir_a_una_cosa(scoped, me):
    coche = Vehicle.objects.create(
        household=scoped, name="Mazda", kind="vehicle", owner=me
    )
    tarjeta = Account.objects.create(
        household=scoped, name="Tarjeta", type=Account.Type.LIABILITY
    )
    gasolina = Account.objects.create(
        household=scoped, name="Gasolina", type=Account.Type.EXPENSE
    )
    form = ExpenseForm({
        "date": "2026-09-18", "description": "Gasolina", "amount": "980",
        "paid_from": tarjeta.pk, "category": gasolina.pk, "about": coche.pk,
    }, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    # Esta dimensión es lo que después permite saber cuánto cuesta el coche.
    apunte = Entry.objects.get().postings.get(amount__gt=0)
    assert apunte.dimension_id == coche.pk


@pytest.mark.django_db
@pytest.mark.parametrize("datos,esperado", [
    ({"periodicity": "monthly", "day": 10}, {"monthly": {"day": 10}}),
    ({"periodicity": "yearly", "day": 31, "month": 3}, {"yearly": {"month": 3, "day": 31}}),
    ({"periodicity": "once", "day": 1, "on_date": "2027-04-30"},
     {"on_date": "2027-04-30"}),
])
def test_la_periodicidad_se_elige_sin_escribir_json(scoped, datos, esperado):
    form = ObligationRuleForm({"label": "Colegiatura", **datos}, household=scoped)
    assert form.is_valid(), form.errors
    assert form.save().schedule == esperado


@pytest.mark.django_db
def test_una_regla_anual_sin_mes_no_se_guarda(scoped):
    form = ObligationRuleForm(
        {"label": "Predial", "periodicity": "yearly", "day": 31}, household=scoped
    )
    assert not form.is_valid()
    assert "en qué mes" in str(form.errors["month"])


@pytest.mark.django_db
def test_la_ficha_muestra_los_datos_del_modulo_primero(scoped, me):
    coche = Vehicle.objects.create(
        household=scoped, name="Mazda CX-5", kind="vehicle", make="Mazda",
        plates="JGT1234", owner=me, status="active", current_value=410000,
    )
    etiquetas = [etiqueta for etiqueta, _ in coche.facts()]
    # Lo que identifica a un coche es la placa, no el estado del registro.
    assert etiquetas.index("Placas") < etiquetas.index("Estado")
    assert "Marca" in etiquetas


@pytest.mark.django_db
def test_editar_desde_la_ficha_conserva_el_tipo(sesion, household):
    from lares.core.scoping import use_household

    sesion.post("/nuevo/vehicle/", {
        "name": "Honda", "plates": "JAB7789", "currency": "MXN", "status": "active",
    })
    with use_household(household):
        coche = Vehicle.objects.get()

    sesion.post(f"/r/{coche.pk}/editar/", {
        "name": "Honda CR-V", "plates": "JAB7789", "currency": "MXN", "status": "active",
    })
    coche.refresh_from_db()
    assert coche.name == "Honda CR-V"
    assert coche.kind == "vehicle"


@pytest.mark.django_db
def test_un_documento_con_vencimiento_avisa_en_cuanto_se_guarda(sesion, household):
    from lares.core.scoping import use_household

    sesion.post("/documentos/nuevo/", {
        "title": "Pasaporte", "doc_type": "passport",
        "expires_on": (dt.date.today() + dt.timedelta(days=200)).isoformat(),
        "confidentiality": "normal",
    })
    with use_household(household):
        assert Document.objects.count() == 1
        assert Obligation.objects.filter(source="core.document_expiry").exists()
