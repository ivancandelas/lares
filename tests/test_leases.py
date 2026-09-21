"""Arrendamiento, en los dos sentidos.

Un contrato es el mismo papel se esté a un lado o al otro de la mesa: mismas
fechas, mismo depósito, mismo incremento anual. Lo único que cambia es quién
cobra y quién paga, y eso es justo lo que aquí se prueba, porque es lo que se
equivoca al leerlo deprisa.

Lo demás que se prueba es lo que de verdad se pierde de vista: un mes que no
llegó, un depósito que nadie devolvió, y cuánto renta un inmueble *después* de
lo que cuesta tenerlo.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Obligation, Party, Posting
from lares.core.services import checks, obligations
from lares.modules.leases.models import Lease, RentPayment
from lares.modules.leases.services import (
    ensure_periods,
    limpiar_lo_anterior,
    next_rent,
    performance,
)
from lares.modules.property.models import Property

HOY = dt.date.today()


def _inmueble(household, **kwargs):
    datos = dict(kind="property", name="Departamento", use=Property.Use.RENTED_OUT,
                 current_value=Decimal("2000000"), currency="MXN")
    datos.update(kwargs)
    return Property.objects.create(household=household, **datos)


def _contrato(household, prop=None, **kwargs):
    datos = dict(kind="lease", name="Contrato", currency="MXN",
                 direction=Lease.Direction.LANDLORD,
                 starts_on=HOY - dt.timedelta(days=200),
                 ends_on=HOY + dt.timedelta(days=200),
                 rent_amount=Decimal("14500"), rent_day=5)
    datos.update(kwargs)
    return Lease.objects.create(household=household,
                                property_ref=prop or _inmueble(household), **datos)


# --- Los dos lados de la mesa -----------------------------------------------


@pytest.mark.django_db
def test_al_arrendador_se_le_dice_que_cobre_y_al_inquilino_que_pague(scoped):
    """Es el único dato que cambia entre los dos, y el más fácil de invertir."""
    mio = _contrato(scoped, direction=Lease.Direction.LANDLORD,
                    prop=_inmueble(scoped, name="Mi departamento"))
    ajeno = _contrato(scoped, direction=Lease.Direction.TENANT, name="Donde vivo",
                      prop=_inmueble(scoped, name="Casa donde vivo",
                                     tenure=Property.Tenure.RENTED,
                                     use=Property.Use.LIVED_IN))
    obligations.materialize(scoped, HOY)

    titulos = list(Obligation.objects.filter(
        source="leases.rent").values_list("title", flat=True))
    assert any(t.startswith("Cobrar") and "Mi departamento" in t for t in titulos)
    assert any(t.startswith("Pagar") and "Casa donde vivo" in t for t in titulos)
    assert mio.is_landlord and not ajeno.is_landlord


@pytest.mark.django_db
def test_no_pagar_urge_mas_que_no_cobrar(scoped):
    """Dejar de pagar te echa de la casa; dejar de cobrar se nota más tarde."""
    _contrato(scoped, direction=Lease.Direction.TENANT)
    obligations.materialize(scoped, HOY)

    renta = Obligation.objects.filter(source="leases.rent").first()
    assert renta.severity == "critical"


@pytest.mark.django_db
def test_un_contrato_no_suma_al_patrimonio(scoped):
    """El inmueble ya cuenta por su lado: sumar el contrato lo contaría dos veces."""
    assert _contrato(scoped).counts_as_asset is False


@pytest.mark.django_db
def test_el_sentido_se_dice_sin_pronombres_ambiguos(scoped):
    """«Lo rento» significa las dos cosas en español; la etiqueta no puede."""
    for etiqueta in dict(Lease.Direction.choices).values():
        assert "mío" in etiqueta          # dice de quién es el inmueble


# --- Los meses --------------------------------------------------------------


@pytest.mark.django_db
def test_se_crea_un_mes_por_cada_mes_de_contrato(scoped):
    contrato = _contrato(scoped, starts_on=HOY.replace(day=1) - dt.timedelta(days=62))

    ensure_periods(contrato)
    assert contrato.payments.count() == 3        # dos meses atrás y el corriente


@pytest.mark.django_db
def test_generar_los_meses_dos_veces_no_los_duplica(scoped):
    contrato = _contrato(scoped)

    ensure_periods(contrato)
    cuantos = contrato.payments.count()
    ensure_periods(contrato)

    assert contrato.payments.count() == cuantos


@pytest.mark.django_db
def test_no_se_generan_meses_despues_de_que_acabe_el_contrato(scoped):
    contrato = _contrato(scoped, ends_on=HOY - dt.timedelta(days=90))

    ensure_periods(contrato)
    assert all(p.due_on <= contrato.ends_on for p in contrato.payments.all())


@pytest.mark.django_db
def test_el_dia_de_pago_31_cae_en_el_ultimo_dia_del_mes(scoped):
    """Febrero no tiene 31: sin esto, generar los meses revienta."""
    contrato = _contrato(scoped, rent_day=31,
                         starts_on=dt.date(HOY.year - 1, 1, 15),
                         ends_on=dt.date(HOY.year - 1, 3, 31))
    ensure_periods(contrato)

    febrero = contrato.payments.get(period=f"{HOY.year - 1}-02")
    assert febrero.due_on.day in (28, 29)


# --- Lo que no llegó --------------------------------------------------------


@pytest.mark.django_db
def test_un_mes_vencido_y_sin_pagar_esta_atrasado(scoped):
    contrato = _contrato(scoped)
    pago = RentPayment.objects.create(
        household=scoped, lease=contrato, period="2020-01",
        due_on=HOY - dt.timedelta(days=10), amount=Decimal("14500"))

    assert pago.is_late(HOY)
    assert pago.days_late(HOY) == 10
    assert contrato.overdue_payments == [pago]


@pytest.mark.django_db
def test_pagar_de_menos_sigue_contando_como_atraso(scoped):
    """Abonar la mitad no salda el mes, y es donde se pierde el resto."""
    contrato = _contrato(scoped)
    pago = RentPayment.objects.create(
        household=scoped, lease=contrato, period="2020-01",
        due_on=HOY - dt.timedelta(days=10), amount=Decimal("14500"),
        paid_on=HOY - dt.timedelta(days=9), amount_paid=Decimal("6000"))

    assert pago.shortfall == 8500
    assert pago.is_late(HOY)


@pytest.mark.django_db
def test_los_meses_sin_cobrar_saltan_como_hueco(scoped):
    contrato = _contrato(scoped, counterpart=Party.objects.create(
        household=scoped, name="Fernanda"))
    for dias in (40, 10):
        RentPayment.objects.create(
            household=scoped, lease=contrato, period=f"2020-{dias:02d}",
            due_on=HOY - dt.timedelta(days=dias), amount=Decimal("14500"))

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "leases.late")
    assert "2 meses sin cobrar" in hallazgo.title
    assert "Fernanda" in hallazgo.detail
    assert hallazgo.severity == "critical"        # el más viejo pasa de 30 días


@pytest.mark.django_db
def test_al_inquilino_se_le_dice_sin_pagar_no_sin_cobrar(scoped):
    contrato = _contrato(scoped, direction=Lease.Direction.TENANT)
    RentPayment.objects.create(household=scoped, lease=contrato, period="2020-01",
                               due_on=HOY - dt.timedelta(days=5),
                               amount=Decimal("14500"))

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "leases.late")
    assert hallazgo.title.startswith("1 mes sin pagar")


# --- El depósito ------------------------------------------------------------


@pytest.mark.django_db
def test_el_deposito_sigue_pendiente_hasta_que_lo_devuelven(scoped):
    contrato = _contrato(scoped, deposit_amount=Decimal("29000"))
    assert contrato.deposit_pending == 29000

    contrato.deposit_returned_on = HOY
    assert contrato.deposit_pending == 0


@pytest.mark.django_db
def test_el_deposito_no_devuelto_al_acabar_el_contrato_salta(scoped):
    """Es dinero tuyo que se evapora en silencio cuando te mudas."""
    _contrato(scoped, direction=Lease.Direction.TENANT,
              ends_on=HOY - dt.timedelta(days=30),
              deposit_amount=Decimal("29000"))

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "leases.deposit")
    assert "29,000" in hallazgo.title


@pytest.mark.django_db
def test_un_contrato_vivo_no_reclama_su_deposito(scoped):
    _contrato(scoped, direction=Lease.Direction.TENANT,
              deposit_amount=Decimal("29000"))

    assert not [f for f in checks.run_all(scoped) if f.check == "leases.deposit"]


# --- El incremento ----------------------------------------------------------


@pytest.mark.django_db
def test_el_incremento_pactado_se_calcula(scoped):
    contrato = _contrato(scoped, increase_kind=Lease.Increase.PERCENT,
                         increase_percent=Decimal("6"), increase_month=1)

    assert next_rent(contrato) == Decimal("15370.00")


@pytest.mark.django_db
def test_el_inpc_no_se_inventa(scoped):
    """Sin el dato oficial, decir un número sería peor que no decir nada."""
    contrato = _contrato(scoped, increase_kind=Lease.Increase.INPC,
                         increase_month=6)

    assert next_rent(contrato) == contrato.rent_amount


@pytest.mark.django_db
def test_el_incremento_avisa_antes_de_que_toque(scoped):
    """Se pierde si nadie lo aplica: no hay quien lo reclame por ti."""
    _contrato(scoped, increase_kind=Lease.Increase.PERCENT,
              increase_percent=Decimal("6"), increase_month=1)
    obligations.materialize(scoped, HOY)

    aviso = Obligation.objects.get(source="leases.increase")
    assert aviso.amount == Decimal("15370.00")
    assert -30 in aviso.remind_offsets


@pytest.mark.django_db
def test_sin_incremento_pactado_no_hay_aviso(scoped):
    _contrato(scoped, increase_kind=Lease.Increase.NONE)
    obligations.materialize(scoped, HOY)

    assert not Obligation.objects.filter(source="leases.increase").exists()


# --- Fin de contrato --------------------------------------------------------


@pytest.mark.django_db
def test_el_fin_de_contrato_avisa_con_noventa_dias(scoped):
    """Renovar o mudarse no se decide en una semana."""
    _contrato(scoped, ends_on=HOY + dt.timedelta(days=200))
    obligations.materialize(scoped, HOY)

    fin = Obligation.objects.get(source="leases.end")
    assert -90 in fin.remind_offsets


@pytest.mark.django_db
def test_un_contrato_acabado_no_genera_nada(scoped):
    _contrato(scoped, ends_on=HOY - dt.timedelta(days=5))
    obligations.materialize(scoped, HOY)

    assert not Obligation.objects.filter(source__startswith="leases.").exists()


# --- Rendimiento ------------------------------------------------------------


@pytest.mark.django_db
def test_el_rendimiento_descuenta_lo_que_cuesta_el_inmueble(scoped):
    """La renta bruta engaña: el predial y el mantenimiento salen de ahí."""
    depto = _inmueble(scoped, current_value=Decimal("2000000"))
    contrato = _contrato(scoped, prop=depto, rent_amount=Decimal("15000"))
    ensure_periods(contrato)
    for pago in contrato.payments.all():
        pago.paid_on, pago.amount_paid = pago.due_on, pago.amount
        pago.save()

    gasto = Account.objects.create(household=scoped, name="Predial",
                                   type=Account.Type.EXPENSE)
    caja = Account.objects.create(household=scoped, name="Banco",
                                  type=Account.Type.ASSET)
    entry = Entry.objects.create(household=scoped, description="Predial", date=HOY)
    Posting.objects.create(household=scoped, entry=entry, account=gasto,
                           amount=Decimal("18000"), currency="MXN", dimension=depto)
    Posting.objects.create(household=scoped, entry=entry, account=caja,
                           amount=Decimal("-18000"), currency="MXN")

    resultado = performance(scoped)[0]
    cobrado = contrato.collected
    assert resultado.annual_rent == cobrado
    assert resultado.annual_costs == 18000
    assert resultado.net == cobrado - 18000
    assert resultado.cap_rate == pytest.approx(float((cobrado - 18000) / 2000000))


@pytest.mark.django_db
def test_lo_que_pagas_de_renta_no_aparece_como_rendimiento(scoped):
    """No rinde el inmueble en el que vives de renta: cuesta."""
    _contrato(scoped, direction=Lease.Direction.TENANT)

    assert performance(scoped) == []


@pytest.mark.django_db
def test_sin_historial_el_rendimiento_se_proyecta_con_la_renta_pactada(scoped):
    contrato = _contrato(scoped, rent_amount=Decimal("15000"))

    assert performance(scoped)[0].annual_rent == 15000 * 12
    assert contrato.collected == 0


@pytest.mark.django_db
def test_un_inmueble_sin_valor_no_finge_una_tasa(scoped):
    depto = _inmueble(scoped, current_value=None, purchase_amount=None)
    _contrato(scoped, prop=depto)

    assert performance(scoped)[0].cap_rate is None


# --- Huecos -----------------------------------------------------------------


@pytest.mark.django_db
def test_un_inmueble_en_renta_sin_contrato_salta(scoped):
    _inmueble(scoped, name="Local vacío", use=Property.Use.RENTED_OUT)

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "leases.no_lease")
    assert "Local vacío" in hallazgo.title


@pytest.mark.django_db
def test_con_contrato_ya_no_salta(scoped):
    depto = _inmueble(scoped, use=Property.Use.RENTED_OUT)
    _contrato(scoped, prop=depto)

    assert not [f for f in checks.run_all(scoped) if f.check == "leases.no_lease"]


# --- Pantallas --------------------------------------------------------------


@pytest.mark.django_db
def test_las_pantallas_de_arrendamiento_abren(sesion_admin, household):
    contrato = _contrato(household)

    for url in ("/arrendamiento/", "/arrendamiento/rendimiento/",
                f"/arrendamiento/{contrato.pk}/"):
        assert sesion_admin.get(url).status_code == 200, url


@pytest.mark.django_db
def test_avisa_si_el_deposito_no_quedo_anotado(scoped):
    """Se entrega una vez y no vuelve a aparecer en ningún recibo."""
    _contrato(scoped, deposit_amount=None)

    claves = {f.check for f in checks.run_all(scoped)}
    assert "leases.no_deposit" in claves


@pytest.mark.django_db
def test_con_el_deposito_anotado_no_avisa(scoped):
    _contrato(scoped, deposit_amount=Decimal("14500"))

    claves = {f.check for f in checks.run_all(scoped)}
    assert "leases.no_deposit" not in claves


@pytest.mark.django_db
def test_se_avisa_del_mes_que_viene_ademas_del_corriente(scoped):
    """Con un solo aviso, el de fin de mes llega cuando ya no da tiempo."""
    _contrato(scoped, direction=Lease.Direction.TENANT, rent_day=5)
    obligations.materialize(scoped, HOY)

    rentas = Obligation.objects.filter(source="leases.rent").order_by("due_on")
    assert rentas.count() == 2
    assert rentas.first().amount == 14500


@pytest.mark.django_db
def test_un_contrato_viejo_no_inventa_cuatro_anos_sin_cobrar(scoped):
    """El peor primer día posible: 48 meses sin cobrar el día del alta.

    Lo que importa no es cuántos meses cree, sino que **ninguno nazca en
    mora**: la deuda de 432.000 que salía no la debía nadie.
    """
    lease = _contrato(scoped, starts_on=HOY - dt.timedelta(days=4 * 365),
                      tracked_from=HOY,
                      prop=_inmueble(scoped, name="Casa Nogal"))
    ensure_periods(lease)

    assert lease.payments.count() <= 1
    assert [p for p in lease.payments.all() if p.is_late()] == []


@pytest.mark.django_db
def test_sin_fecha_de_control_se_comporta_como_siempre(scoped):
    """Las instalaciones que ya existen no cambian de conducta solas."""
    lease = _contrato(scoped, starts_on=HOY - dt.timedelta(days=365),
                      tracked_from=None)
    ensure_periods(lease)

    assert lease.payments.count() >= 12


@pytest.mark.django_db
def test_poner_al_dia_borra_lo_intacto_y_respeta_lo_anotado(scoped):
    """Un mes con cobro anotado es un dato de alguien: no se borra por una fecha."""
    lease = _contrato(scoped, starts_on=HOY - dt.timedelta(days=365),
                      tracked_from=None)
    ensure_periods(lease)
    antes = lease.payments.count()
    assert antes >= 12

    cobrado = lease.payments.order_by("due_on").first()
    cobrado.paid_on = cobrado.due_on
    cobrado.amount_paid = Decimal("9000")
    cobrado.save()

    lease.tracked_from = HOY
    lease.save()
    borrados = limpiar_lo_anterior(lease)

    assert borrados == antes - 1
    assert lease.payments.filter(pk=cobrado.pk).exists()


@pytest.mark.django_db
def test_bajar_la_fecha_recupera_los_meses(scoped):
    """Borrar tiene que ser reversible, o nadie se atreve a pulsar el botón."""
    lease = _contrato(scoped, starts_on=HOY - dt.timedelta(days=365),
                      tracked_from=HOY)
    ensure_periods(lease)
    limpiar_lo_anterior(lease)
    assert lease.payments.count() <= 1

    lease.tracked_from = None
    lease.save()
    ensure_periods(lease)

    assert lease.payments.count() >= 12
