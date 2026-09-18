"""Cartera de inmuebles.

Lo que se prueba es la distinción que obliga a rehacer el módulo si se ignora:
tenencia (qué relación tienes con él) y uso (qué se hace con él) son ejes
distintos, y un inmueble que no es tuyo no es patrimonio aunque lo administres.
"""

import datetime as dt

import pytest

from lares.core.models import Obligation, Party, Resource
from lares.core.services import checks, obligations
from lares.modules.property.models import Property, Service

HOY = dt.date(2026, 9, 18)


@pytest.fixture
def casa_rentada(scoped, me):
    casero = Party.objects.create(household=scoped, name="Sr. Ramírez")
    return Property.objects.create(
        household=scoped, name="Casa de Providencia", kind="property",
        property_type=Property.Type.HOUSE, tenure=Property.Tenure.RENTED,
        use=Property.Use.LIVED_IN, owner=me, landlord=casero,
        rent_amount=18500, rent_due_day=5, deposit_amount=37000,
        lease_ends_on=HOY + dt.timedelta(days=100), currency="MXN",
    )


@pytest.fixture
def depto(scoped, me):
    return Property.objects.create(
        household=scoped, name="Departamento en Chapalita", kind="property",
        property_type=Property.Type.APARTMENT, tenure=Property.Tenure.OWNED,
        use=Property.Use.RENTED_OUT, owner=me, current_value=2900000,
        predial_month=1, predial_amount=4800, currency="MXN",
    )


# --- Tenencia y uso son ejes distintos --------------------------------------


@pytest.mark.django_db
def test_lo_rentado_no_suma_al_patrimonio(scoped, casa_rentada):
    """Vives ahí y pagas todo, pero lo devuelves al acabar el contrato."""
    casa_rentada.current_value = 5000000        # aunque alguien lo rellene
    casa_rentada.save()

    assert not casa_rentada.is_mine
    assert not casa_rentada.counts_as_asset


@pytest.mark.django_db
def test_lo_propio_suma_aunque_lo_tengas_rentado_a_otro(scoped, depto):
    assert depto.use == Property.Use.RENTED_OUT
    assert depto.is_mine
    assert depto.counts_as_asset


@pytest.mark.django_db
def test_la_copropiedad_es_tuya(scoped, me):
    terreno = Property.objects.create(
        household=scoped, name="Terreno", kind="property",
        property_type=Property.Type.LAND, tenure=Property.Tenure.CO_OWNED,
        ownership_share=50, owner=me,
    )
    assert terreno.counts_as_asset


# --- Lo que genera cada situación -------------------------------------------


@pytest.mark.django_db
def test_si_vives_de_renta_el_pago_es_una_obligacion(scoped, casa_rentada):
    obligations.materialize(scoped, HOY)

    pagos = Obligation.objects.filter(source="property.rent",
                                      title__startswith="Renta")
    assert pagos.count() == 2                    # el próximo y el siguiente
    assert pagos.first().amount == 18500
    assert pagos.first().severity == "critical"
    assert str(pagos.first().counterparty) == "Sr. Ramírez"


@pytest.mark.django_db
def test_el_fin_del_contrato_avisa_con_tres_meses(scoped, casa_rentada):
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.get(title__startswith="Acaba el contrato")
    assert aviso.due_on == casa_rentada.lease_ends_on
    # Renovar o mudarse no se decide en una semana.
    assert min(aviso.remind_offsets) == -90


@pytest.mark.django_db
def test_el_predial_lo_paga_el_dueno_no_el_inquilino(scoped, casa_rentada, depto):
    """El predial viene del pack, con `only_if: {is_mine: true}`."""
    obligations.materialize(scoped, HOY)

    prediales = Obligation.objects.filter(title__startswith="Predial")
    assert prediales.exists()
    for p in prediales:
        assert "Chapalita" in p.title          # nunca el que rentas


@pytest.mark.django_db
def test_los_servicios_siguen_su_propio_ciclo(scoped, casa_rentada):
    Service.objects.create(
        household=scoped, name="Agua", kind="service",
        service_kind=Service.Kind.WATER, property_ref=casa_rentada,
        cycle=Service.Cycle.BIMONTHLY, due_day=20, typical_amount=640,
    )
    obligations.materialize(scoped, HOY)

    recibos = list(Obligation.objects.filter(source="property.service").order_by("due_on"))
    assert len(recibos) == 2
    # Bimestral: dos meses entre uno y otro, no uno.
    diferencia = (recibos[1].due_on.year - recibos[0].due_on.year) * 12 + \
                 (recibos[1].due_on.month - recibos[0].due_on.month)
    assert diferencia == 2


@pytest.mark.django_db
def test_un_servicio_no_es_patrimonio(scoped, casa_rentada):
    luz = Service.objects.create(
        household=scoped, name="Luz", kind="service", property_ref=casa_rentada,
        service_kind=Service.Kind.POWER, current_value=9999,
    )
    assert not luz.counts_as_asset


# --- Huecos -----------------------------------------------------------------


@pytest.mark.django_db
def test_avisa_de_un_inmueble_propio_sin_escritura(scoped, depto):
    claves = {f.check for f in checks.run_all(scoped)}
    assert "property.no_deed" in claves


@pytest.mark.django_db
def test_no_pide_escritura_de_lo_que_no_es_tuyo(scoped, casa_rentada):
    hallazgos = [f for f in checks.run_all(scoped) if f.check == "property.no_deed"]
    assert hallazgos == []


@pytest.mark.django_db
def test_avisa_si_no_registraste_el_deposito(scoped, casa_rentada):
    casa_rentada.deposit_amount = None
    casa_rentada.save()

    claves = {f.check for f in checks.run_all(scoped)}
    assert "property.no_deposit" in claves


@pytest.mark.django_db
def test_un_terreno_no_necesita_seguro_de_casa(scoped, me):
    Property.objects.create(
        household=scoped, name="Terreno", kind="property",
        property_type=Property.Type.LAND, tenure=Property.Tenure.OWNED, owner=me,
    )
    hallazgos = [f for f in checks.run_all(scoped) if f.check == "property.no_insurance"]
    assert hallazgos == []


@pytest.mark.django_db
def test_el_patrimonio_separa_lo_que_administras_de_lo_que_es_tuyo(
    client, django_user_model, household, scoped, casa_rentada, depto
):
    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    client.force_login(user)
    contenido = client.get("/patrimonio/").content.decode()

    assert "Administras, pero no son tuyos" in contenido
    # El valor sumado es solo el del departamento, no el de la casa rentada.
    activos = Resource.objects.filter(status=Resource.Status.ACTIVE)
    total = sum(r.current_value or 0 for r in activos if r.as_concrete().counts_as_asset)
    assert total == 2900000
