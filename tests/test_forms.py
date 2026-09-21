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
        # El refrendo lo aporta el pack de jurisdicción, no el módulo.
        assert Obligation.objects.filter(title__startswith="Refrendo").exists()


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


@pytest.mark.django_db
def test_una_organizacion_no_cumple_anos(household):
    """El campo viaja igual, pero no se pinta y no se guarda."""
    from lares.core.forms import PartyForm
    from lares.core.models import Party

    form = PartyForm({
        "kind": Party.Kind.ORGANIZATION, "name": "Ferretería El Tornillo",
        "birth_date": "1980-05-01",
    }, household=household)

    assert form.is_valid(), form.errors
    assert form.save().birth_date is None


@pytest.mark.django_db
def test_una_persona_si_conserva_su_fecha(household):
    import datetime as dt

    from lares.core.forms import PartyForm
    from lares.core.models import Party

    form = PartyForm({
        "kind": Party.Kind.PERSON, "name": "Iván", "birth_date": "1980-05-01",
    }, household=household)

    assert form.is_valid(), form.errors
    assert form.save().birth_date == dt.date(1980, 5, 1)


@pytest.mark.django_db
def test_el_banco_de_una_tarjeta_solo_ofrece_organizaciones(household):
    """Entre cincuenta contactos hay que encontrar el banco."""
    from lares.core.models import Party
    from lares.modules.finance.forms import CreditCardForm

    banco = Party.objects.create(household=household, name="BBVA",
                                 kind=Party.Kind.ORGANIZATION)
    suegra = Party.objects.create(household=household, name="Suegra",
                                  kind=Party.Kind.PERSON)

    ofrecidos = CreditCardForm(household=household).fields["issuer"].queryset

    assert banco in ofrecidos
    assert suegra not in ofrecidos


@pytest.mark.django_db
def test_el_titular_de_una_tarjeta_si_puede_ser_una_empresa(household):
    """Una tarjeta empresarial va a nombre de la empresa, no de quien la lleva."""
    from lares.core.models import Party
    from lares.modules.finance.forms import CreditCardForm

    empresa = Party.objects.create(household=household, name="Mi S.A. de C.V.",
                                   kind=Party.Kind.ORGANIZATION)

    assert empresa in CreditCardForm(household=household).fields["owner"].queryset


@pytest.mark.django_db
def test_la_cuenta_de_una_tarjeta_solo_ofrece_pasivos(household):
    """Colgarla de la nómina contaba cada compra dos veces."""
    from lares.core.models import Account
    from lares.modules.finance.forms import CreditCardForm

    deuda = Account.objects.create(household=household, name="Tarjeta BBVA",
                                   type=Account.Type.LIABILITY)
    nomina = Account.objects.create(household=household, name="Nómina",
                                    type=Account.Type.ASSET)

    ofrecidas = CreditCardForm(household=household).fields["account"].queryset

    assert deuda in ofrecidas
    assert nomina not in ofrecidas


@pytest.mark.django_db
def test_una_cuenta_de_debito_arranca_con_lo_que_ya_tiene(scoped):
    """Nadie empieza a usar esto el día que nació."""
    from decimal import Decimal

    from lares.core.forms import AccountForm
    from lares.core.models import Account

    form = AccountForm({
        "name": "Nómina", "type": Account.Type.ASSET, "currency": "MXN",
        "opening_balance": "14500", "opening_date": "2026-09-21",
    }, household=scoped)

    assert form.is_valid(), form.errors
    assert form.save().balance == Decimal("14500")


@pytest.mark.django_db
def test_una_tarjeta_arranca_debiendo_y_no_a_favor(scoped):
    """El signo es la trampa: un pasivo vive en negativo en el libro.

    Sin darle la vuelta, la tarjeta que debe 3.000 aparecería como 3.000 a
    favor y el patrimonio saldría 6.000 de más.
    """
    from decimal import Decimal

    from lares.core.forms import AccountForm
    from lares.core.models import Account

    form = AccountForm({
        "name": "Tarjeta BBVA", "type": Account.Type.LIABILITY,
        "currency": "MXN", "opening_balance": "3000",
        "opening_date": "2026-09-21",
    }, household=scoped)

    assert form.is_valid(), form.errors
    assert form.save().balance == Decimal("3000")


@pytest.mark.django_db
def test_el_saldo_inicial_no_es_ingreso_ni_gasto(scoped):
    """Si entrara como ingreso, «de dónde viene el dinero» mentiría siempre."""
    from lares.core.forms import AccountForm
    from lares.core.models import Account

    AccountForm({
        "name": "Nómina", "type": Account.Type.ASSET, "currency": "MXN",
        "opening_balance": "14500", "opening_date": "2026-09-21",
    }, household=scoped).save()

    contrapartida = Account.objects.get(name=AccountForm.SALDO_INICIAL)
    assert contrapartida.type == Account.Type.EQUITY
    assert not Account.objects.filter(
        type__in=[Account.Type.INCOME, Account.Type.EXPENSE]).exists()


@pytest.mark.django_db
def test_el_asiento_del_saldo_inicial_cuadra(scoped):
    """Un asiento que no suma cero rompe el libro entero."""
    from django.db.models import Sum

    from lares.core.forms import AccountForm
    from lares.core.models import Account, Entry

    AccountForm({
        "name": "Tarjeta", "type": Account.Type.LIABILITY, "currency": "MXN",
        "opening_balance": "3000", "opening_date": "2026-09-21",
    }, household=scoped).save()

    entry = Entry.objects.get(source="opening")
    assert entry.postings.aggregate(t=Sum("amount"))["t"] == 0


@pytest.mark.django_db
def test_sin_saldo_inicial_no_se_inventa_un_asiento(scoped):
    from lares.core.forms import AccountForm
    from lares.core.models import Account, Entry

    AccountForm({"name": "Ahorro", "type": Account.Type.ASSET,
                 "currency": "MXN"}, household=scoped).save()

    assert not Entry.objects.exists()
    assert not Account.objects.filter(type=Account.Type.EQUITY).exists()


@pytest.mark.django_db
def test_una_categoria_no_tiene_saldo_inicial(scoped):
    """«Supermercado» no arranca con nada: es una categoría, no una cuenta."""
    from lares.core.forms import AccountForm
    from lares.core.models import Account, Entry

    form = AccountForm({
        "name": "Supermercado", "type": Account.Type.EXPENSE,
        "currency": "MXN", "opening_balance": "500",
        "opening_date": "2026-09-21",
    }, household=scoped)

    assert form.is_valid(), form.errors
    form.save()
    assert not Entry.objects.exists()


@pytest.mark.django_db
def test_editar_una_cuenta_no_reescribe_su_saldo(scoped):
    """El libro es inmutable: un saldo que se puede reescribir deja de cuadrar."""
    from lares.core.forms import AccountForm
    from lares.core.models import Account

    cuenta = Account.objects.create(household=scoped, name="Nómina",
                                    type=Account.Type.ASSET)

    assert "opening_balance" not in AccountForm(instance=cuenta,
                                                household=scoped).fields


@pytest.mark.django_db
def test_las_fechas_se_pintan_en_iso_o_el_navegador_las_deja_en_blanco(scoped):
    """Un `<input type="date">` solo entiende AAAA-MM-DD.

    Con el formato local -18/09/2026- el navegador da el valor por inválido y
    pinta el campo vacío. Se comía dos cosas sin un solo error visible: el
    «hoy» de registrar un gasto nunca aparecía, y al editar una ficha salían
    en blanco todas sus fechas, así que guardar borraba las opcionales.
    """
    import datetime as dt

    from lares.core.forms import ObligationRuleForm

    form = ObligationRuleForm(household=scoped,
                              initial={"on_date": dt.date(2026, 9, 18)})

    assert 'value="2026-09-18"' in str(form["on_date"])
    assert 'type="date"' in str(form["on_date"])
