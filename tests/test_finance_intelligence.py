"""Lo que el libro permite responder y una tabla de movimientos no.

Tres preguntas: cuánto es mío para gastar, cuánto me cuesta esto de verdad, y
si me alcanza en marzo.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Obligation, Posting, Resource
from lares.core.scoping import use_household
from lares.modules.finance import services
from lares.modules.finance.models_provision import Provision
from lares.modules.vehicles.models import Vehicle

HOY = dt.date.today()


@pytest.fixture
def libro(scoped, me):
    cuentas = {
        "nomina": Account.objects.create(household=scoped, name="Nómina",
                                         type=Account.Type.ASSET),
        "sueldo": Account.objects.create(household=scoped, name="Sueldo",
                                         type=Account.Type.INCOME),
        "auto": Account.objects.create(household=scoped, name="Vehículo",
                                       type=Account.Type.EXPENSE),
    }
    mazda = Vehicle.objects.create(household=scoped, name="Mazda CX-5",
                                   kind="vehicle", owner=me)
    return cuentas, mazda


def _mover(household, cuentas, origen, destino, importe, dias=1, sobre=None):
    entry = Entry.objects.create(household=household, date=HOY - dt.timedelta(days=dias),
                                 description="Movimiento")
    Posting.objects.create(household=household, entry=entry, account=destino,
                           amount=importe, dimension=sobre)
    Posting.objects.create(household=household, entry=entry, account=origen,
                           amount=-importe)
    return entry


# --- El escollo de la herencia multi-tabla ----------------------------------


@pytest.mark.django_db
def test_as_concrete_funciona_fuera_de_una_peticion(scoped, libro):
    """Devolvía el padre en silencio, y todo lo que depende del tipo salía a cero."""
    _, mazda = libro
    como_padre = Resource.all_objects.get(pk=mazda.pk)

    # Sin contexto de hogar: es justo donde fallaba.
    assert como_padre.as_concrete().__class__ is Vehicle


@pytest.mark.django_db
def test_la_dimension_se_guarda_contra_el_tipo_concreto(scoped, libro):
    """Si unas veces se guarda el padre y otras la hija, el historial se parte."""
    from django.contrib.contenttypes.models import ContentType

    cuentas, mazda = libro
    como_padre = Resource.objects.get(pk=mazda.pk)
    _mover(scoped, cuentas, cuentas["nomina"], cuentas["auto"], 980, sobre=como_padre)

    apunte = Posting.objects.get(amount=980)
    assert apunte.dimension_type == ContentType.objects.get_for_model(Vehicle)


# --- Cuánto me cuesta esto de verdad ----------------------------------------


@pytest.mark.django_db
def test_el_coste_de_tener_algo_sale_del_libro(scoped, libro):
    cuentas, mazda = libro
    _mover(scoped, cuentas, cuentas["nomina"], cuentas["auto"], 980, sobre=mazda)
    _mover(scoped, cuentas, cuentas["nomina"], cuentas["auto"], 4750, dias=60, sobre=mazda)
    _mover(scoped, cuentas, cuentas["nomina"], cuentas["auto"], 2000, dias=5)  # sin atribuir

    coste = services.cost_of(mazda)
    assert coste["total"] == 5730           # solo lo atribuido al coche
    assert coste["lines"][0].label == "Vehículo"


@pytest.mark.django_db
def test_el_coste_se_puede_pedir_sin_contexto_de_hogar(scoped, libro):
    cuentas, mazda = libro
    _mover(scoped, cuentas, cuentas["nomina"], cuentas["auto"], 980, sobre=mazda)

    from lares.core.scoping import use_household as _uh

    with _uh(None):
        assert services.cost_of(mazda)["total"] == 980


@pytest.mark.django_db
def test_los_trabajos_sin_asentar_se_listan_aparte(scoped, libro):
    """Sumarlos sería contar lo mismo por dos caminos."""
    from django.contrib.contenttypes.models import ContentType

    from lares.modules.maintenance.models import WorkOrder

    cuentas, mazda = libro
    WorkOrder.objects.create(
        household=scoped, title="Afinación", done_on=HOY - dt.timedelta(days=30),
        cost=4750, subject_type=ContentType.objects.get_for_model(Vehicle),
        subject_id=mazda.pk,
    )
    coste = services.cost_of(mazda)

    assert coste["total"] == 0              # no se suman
    assert len(coste["unbooked"]) == 1      # pero se ven


# --- Cuánto es mío para gastar ----------------------------------------------


@pytest.mark.django_db
def test_lo_apartado_deja_de_contar_como_disponible(scoped, libro):
    cuentas, _ = libro
    _mover(scoped, cuentas, cuentas["sueldo"], cuentas["nomina"], 42000)
    Provision.objects.create(household=scoped, name="Predial",
                             account=cuentas["nomina"], target_amount=9000,
                             saved_amount=9000, due_on=HOY + dt.timedelta(days=120))

    datos = services.available(scoped)
    assert datos["in_accounts"] == 42000
    assert datos["reserved"] == 9000
    assert datos["available"] == 33000       # el saldo del banco miente


@pytest.mark.django_db
def test_avisa_de_lo_que_falta_por_apartar(scoped, libro):
    cuentas, _ = libro
    Provision.objects.create(household=scoped, name="Colegiatura",
                             account=cuentas["nomina"], target_amount=15000,
                             saved_amount=6000)

    assert services.available(scoped)["shortfall"] == 9000


@pytest.mark.django_db
def test_dice_cuanto_apartar_cada_mes(scoped, libro):
    cuentas, _ = libro
    p = Provision.objects.create(
        household=scoped, name="Predial", account=cuentas["nomina"],
        target_amount=Decimal("9000"), saved_amount=Decimal("3000"),
        due_on=HOY + dt.timedelta(days=90),
    )
    assert p.missing == 6000
    assert p.monthly_needed is not None and p.monthly_needed > 0


# --- Qué merece una provisión -----------------------------------------------


@pytest.mark.django_db
def test_no_propone_apartar_para_lo_que_se_paga_cada_mes(scoped, libro):
    """Eso es flujo: se paga del ingreso del mes. Apartarlo sería contarlo dos veces."""
    cuentas, _ = libro
    _mover(scoped, cuentas, cuentas["sueldo"], cuentas["nomina"], 42000)
    for mes in (1, 2):
        Obligation.objects.create(
            household=scoped, dedupe_key=f"luz:{mes}", title="Recibo de luz",
            due_on=HOY + dt.timedelta(days=50 + 30 * mes), amount=1180,
            source="property.service", subject_id=None,
        )

    assert services.suggest_provisions(scoped) == []


@pytest.mark.django_db
def test_propone_apartar_para_lo_anual_y_grande(scoped, libro):
    cuentas, _ = libro
    _mover(scoped, cuentas, cuentas["sueldo"], cuentas["nomina"], 42000)
    Obligation.objects.create(
        household=scoped, dedupe_key="predial:2027", title="Predial 2027",
        due_on=HOY + dt.timedelta(days=120), amount=4800, source="packs.property",
    )

    sugeridas = services.suggest_provisions(scoped)
    assert [o.title for o in sugeridas] == ["Predial 2027"]


@pytest.mark.django_db
def test_no_propone_dos_veces_lo_ya_apartado(scoped, libro):
    cuentas, _ = libro
    Obligation.objects.create(
        household=scoped, dedupe_key="predial:2027", title="Predial 2027",
        due_on=HOY + dt.timedelta(days=120), amount=4800, source="packs.property",
    )
    Provision.objects.create(household=scoped, name="Predial",
                             account=cuentas["nomina"], target_amount=4800,
                             source_key="predial:2027")

    assert services.suggest_provisions(scoped) == []


# --- ¿Me alcanza? -----------------------------------------------------------


@pytest.mark.django_db
def test_la_proyeccion_avisa_del_mes_en_que_te_quedas_corto(scoped, libro):
    cuentas, _ = libro
    _mover(scoped, cuentas, cuentas["sueldo"], cuentas["nomina"], 3000, dias=10)
    Obligation.objects.create(
        household=scoped, dedupe_key="grande", title="Algo caro",
        due_on=HOY + dt.timedelta(days=45), amount=50000, source="x",
    )

    flujo = services.cash_flow(scoped, months=4)
    assert flujo["goes_negative"]
    assert flujo["worst"].balance < 0


@pytest.mark.django_db
def test_la_proyeccion_estima_el_ingreso_con_los_ultimos_tres_meses(scoped, libro):
    cuentas, _ = libro
    for dias in (10, 40, 70):
        _mover(scoped, cuentas, cuentas["sueldo"], cuentas["nomina"], 30000, dias=dias)

    assert services.cash_flow(scoped)["monthly_income"] == 30000


@pytest.mark.django_db
def test_la_proyeccion_parte_del_disponible_no_del_saldo(scoped, libro):
    cuentas, _ = libro
    _mover(scoped, cuentas, cuentas["sueldo"], cuentas["nomina"], 42000)
    Provision.objects.create(household=scoped, name="Predial",
                             account=cuentas["nomina"], target_amount=9000,
                             saved_amount=9000)

    assert services.cash_flow(scoped)["start"] == 33000


@pytest.mark.django_db
def test_el_fin_de_una_permanencia_no_cuenta_como_dinero(scoped, libro):
    """Ese día no vence dinero, vence una atadura."""
    from lares.modules.subscriptions.models import Subscription

    cuentas, _ = libro
    Subscription.objects.create(
        household=scoped, name="Gimnasio", kind="subscription", amount=899,
        cycle=Subscription.Cycle.MONTHLY, charge_day=1,
        commitment_until=HOY + dt.timedelta(days=70), currency="MXN",
    )
    from lares.core.services import obligations as motor

    motor.materialize(scoped, HOY)

    with use_household(scoped):
        aviso = Obligation.objects.get(source="subscriptions.commitment")
    assert aviso.amount is None
