"""Lo que tienes contratado.

Nadie cancela lo que no recuerda tener. Lo que se prueba aquí es lo que cambia
decisiones: el coste anual, y la diferencia entre una cuenta tuya y una que solo
pagas.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Obligation, Party
from lares.core.services import checks, obligations
from lares.modules.subscriptions.models import Subscription

HOY = dt.date.today()


def _sub(household, **kwargs):
    datos = dict(kind="subscription", name="Netflix", amount=Decimal("219"),
                 cycle=Subscription.Cycle.MONTHLY, charge_day=14, currency="MXN")
    datos.update(kwargs)
    return Subscription.objects.create(household=household, **datos)


# --- El número que nadie tiene a mano ---------------------------------------


@pytest.mark.django_db
def test_el_coste_anual_es_lo_que_cambia_la_decision(scoped):
    """«219 al mes» se lee como 219. Al año son 2.628."""
    mensual = _sub(scoped, amount=Decimal("219"), cycle=Subscription.Cycle.MONTHLY)
    assert mensual.yearly_cost == Decimal("2628")


@pytest.mark.django_db
def test_compara_ciclos_distintos_en_la_misma_escala(scoped):
    """Un VPS anual y un streaming mensual solo se comparan al año."""
    anual = _sub(scoped, name="VPS", amount=Decimal("1180"),
                 cycle=Subscription.Cycle.YEARLY)
    mensual = _sub(scoped, name="Disney+", amount=Decimal("189"),
                   cycle=Subscription.Cycle.MONTHLY)

    assert anual.yearly_cost == Decimal("1180")
    assert mensual.yearly_cost == Decimal("2268")
    # El que parecía más barato al mes cuesta más al año.
    assert mensual.yearly_cost > anual.yearly_cost


@pytest.mark.django_db
def test_el_coste_mensual_equivalente_sale_del_anual(scoped):
    anual = _sub(scoped, name="VPS", amount=Decimal("1200"),
                 cycle=Subscription.Cycle.YEARLY)
    assert anual.monthly_cost == Decimal("100")


# --- De quién es la cuenta --------------------------------------------------


@pytest.mark.django_db
def test_una_cuenta_ajena_se_paga_pero_no_se_cancela(scoped):
    """La de tu hijo es suya; el sistema no puede sugerirte cancelarla sin más."""
    hijo = Party.objects.create(household=scoped, name="Diego")
    icloud = _sub(scoped, name="iCloud de Diego", amount=Decimal("49"),
                  access=Subscription.Access.THEIRS, account_holder=hijo)

    assert not icloud.is_mine_to_cancel
    assert "a nombre de Diego" in icloud.context_line()


@pytest.mark.django_db
def test_una_cuenta_compartida_sigue_siendo_tuya_para_cancelar(scoped):
    assert _sub(scoped, access=Subscription.Access.SHARED).is_mine_to_cancel


@pytest.mark.django_db
def test_un_contrato_no_es_patrimonio(scoped):
    assert not _sub(scoped).counts_as_asset


# --- Avisos -----------------------------------------------------------------


@pytest.mark.django_db
def test_el_cargo_aparece_antes_de_llegar(scoped):
    proveedor = Party.objects.create(household=scoped, name="Netflix",
                                     kind=Party.Kind.ORGANIZATION)
    _sub(scoped, provider=proveedor)
    obligations.materialize(scoped, HOY)

    cargo = Obligation.objects.filter(source="subscriptions.charge").first()
    assert cargo.amount == Decimal("219")
    assert str(cargo.counterparty) == "Netflix"
    # Solo hay que saberlo, no hacer nada: un aviso corto basta.
    assert cargo.remind_offsets == [-2]


@pytest.mark.django_db
def test_el_fin_de_la_permanencia_avisa_con_mes_y_medio(scoped):
    """Es el único momento con poder de negociación."""
    _sub(scoped, name="Gimnasio", amount=Decimal("899"),
         commitment_until=HOY + dt.timedelta(days=70))
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.get(source="subscriptions.commitment")
    assert min(aviso.remind_offsets) == -45
    # Sin importe: ese día no vence dinero, vence una atadura. Ponerle el coste
    # anual lo colaría en las provisiones y en la proyección de flujo.
    assert aviso.amount is None
    assert Decimal(aviso.extra["yearly_cost"]) == Decimal("10788")


@pytest.mark.django_db
def test_una_permanencia_ya_pasada_no_genera_ruido(scoped):
    _sub(scoped, commitment_until=HOY - dt.timedelta(days=10))
    obligations.materialize(scoped, HOY)
    assert not Obligation.objects.filter(source="subscriptions.commitment").exists()


# --- Huecos -----------------------------------------------------------------


@pytest.mark.django_db
def test_avisa_de_la_subida_de_precio_en_terminos_anuales(scoped):
    _sub(scoped, amount=Decimal("219"), previous_amount=Decimal("199"),
         price_changed_on=HOY - dt.timedelta(days=95))

    hallazgos = [f for f in checks.run_all(scoped)
                 if f.check == "subscriptions.price_rose"]
    assert hallazgos
    # 20 más por cargo son 240 al año: así se entiende si compensa.
    assert "240" in hallazgos[0].detail


@pytest.mark.django_db
def test_si_la_cuenta_no_es_tuya_el_aviso_lo_dice(scoped):
    hijo = Party.objects.create(household=scoped, name="Diego")
    _sub(scoped, name="iCloud", amount=Decimal("59"), previous_amount=Decimal("49"),
         access=Subscription.Access.THEIRS, account_holder=hijo)

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "subscriptions.price_rose")
    assert "La cuenta no es tuya" in hallazgo.detail


@pytest.mark.django_db
def test_bajar_de_precio_no_es_un_hueco(scoped):
    _sub(scoped, amount=Decimal("199"), previous_amount=Decimal("219"))
    claves = {f.check for f in checks.run_all(scoped)}
    assert "subscriptions.price_rose" not in claves


@pytest.mark.django_db
def test_avisa_si_no_sabes_con_que_tarjeta_pagas(scoped):
    _sub(scoped, paid_with=None)
    claves = {f.check for f in checks.run_all(scoped)}
    assert "subscriptions.no_payment" in claves


@pytest.mark.django_db
def test_deja_de_avisar_cuando_el_metodo_de_pago_esta(scoped):
    tarjeta = Account.objects.create(household=scoped, name="Tarjeta",
                                     type=Account.Type.LIABILITY)
    _sub(scoped, paid_with=tarjeta)
    claves = {f.check for f in checks.run_all(scoped)}
    assert "subscriptions.no_payment" not in claves


@pytest.mark.django_db
def test_pregunta_por_lo_que_llevas_un_ano_sin_revisar(scoped):
    from lares.core.models import Resource

    sub = _sub(scoped, amount=Decimal("899"))
    Resource.objects.filter(pk=sub.pk).update(
        verified_on=HOY - dt.timedelta(days=400))

    hallazgos = [f for f in checks.run_all(scoped)
                 if f.check == "subscriptions.review"]
    assert hallazgos
    assert "10,788" in hallazgos[0].detail      # lo que suman al año


# --- Enlaces de ficha -------------------------------------------------------


@pytest.mark.django_db
def test_la_ficha_del_hijo_ensena_lo_que_le_pagas(scoped):
    from lares.core.registry import registry

    hijo = Party.objects.create(household=scoped, name="Diego")
    _sub(scoped, name="iCloud", amount=Decimal("49"),
         access=Subscription.Access.THEIRS, account_holder=hijo)

    enlaces = {e.label: e for e in registry.links_for(hijo)}
    assert "cuenta que le pagas" in enlaces
    assert "$588" in enlaces["cuenta que le pagas"].hint
