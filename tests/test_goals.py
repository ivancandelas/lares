"""Metas.

Lo que separa una meta de una lista de deseos es la proyección: no «llevas el
45%», sino «a este ritmo llegarías siete meses tarde». Eso obliga a medir el
ritmo real, y ahí las dos clases de meta se miden distinto a propósito:

    juntar   →  por lo que de verdad apartaste
    saldar   →  por lo que de verdad sigues debiendo

Medir una deuda por los abonos mentiría, y ese es el caso que más se prueba
aquí: pagas puntual, sigues cargando, y la barra diría que vas bien.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Posting
from lares.core.services import checks
from lares.modules.goals.models import Goal, GoalContribution

HOY = dt.date.today()


def _hace(meses: int) -> dt.date:
    total = HOY.month - 1 - meses
    return dt.date(HOY.year + total // 12, total % 12 + 1, 1)


def _meta(household, **kwargs):
    datos = dict(name="Enganche", kind=Goal.Kind.SAVE,
                 target_amount=Decimal("100000"), currency="MXN",
                 started_on=_hace(12))
    datos.update(kwargs)
    return Goal.objects.create(household=household, **datos)


def _aportar(household, meta, cuantas, importe, cada_mes_desde=None):
    inicio = cada_mes_desde if cada_mes_desde is not None else cuantas
    for i in range(cuantas):
        GoalContribution.objects.create(
            household=household, goal=meta, date=_hace(inicio - i),
            amount=Decimal(importe))


def _deuda(household, saldo, nombre="Tarjeta"):
    """Una cuenta de pasivo con saldo real, hecho de apuntes."""
    cuenta = Account.objects.create(household=household, name=nombre,
                                    type=Account.Type.LIABILITY)
    gasto = Account.objects.create(household=household, name=f"Gasto {nombre}",
                                   type=Account.Type.EXPENSE)
    entry = Entry.objects.create(household=household, description="Compras",
                                 date=_hace(12))
    Posting.objects.create(household=household, entry=entry, account=gasto,
                           amount=Decimal(saldo), currency="MXN")
    Posting.objects.create(household=household, entry=entry, account=cuenta,
                           amount=-Decimal(saldo), currency="MXN")
    return cuenta


def _abonar(household, cuenta, importe, cuando):
    caja = Account.objects.create(household=household,
                                  name=f"Banco {cuando}", type=Account.Type.ASSET)
    entry = Entry.objects.create(household=household, description="Abono",
                                 date=cuando)
    Posting.objects.create(household=household, entry=entry, account=cuenta,
                           amount=Decimal(importe), currency="MXN")
    Posting.objects.create(household=household, entry=entry, account=caja,
                           amount=-Decimal(importe), currency="MXN")


# --- Dónde vas --------------------------------------------------------------


@pytest.mark.django_db
def test_lo_apartado_cuenta_junto_con_lo_que_ya_tenias(scoped):
    meta = _meta(scoped, baseline_amount=Decimal("30000"))
    _aportar(scoped, meta, 3, 5000)

    assert meta.current == 45000
    assert meta.progress == pytest.approx(0.45)
    assert meta.missing == 55000


@pytest.mark.django_db
def test_una_meta_cumplida_no_pasa_del_cien_por_ciento(scoped):
    meta = _meta(scoped, target_amount=Decimal("10000"))
    _aportar(scoped, meta, 1, 25000)

    assert meta.is_reached
    assert meta.progress == 1.0
    assert meta.missing == 0


# --- Una deuda se mide por el saldo, no por los abonos ----------------------


@pytest.mark.django_db
def test_la_deuda_se_lee_del_saldo(scoped):
    cuenta = _deuda(scoped, 48000)
    meta = _meta(scoped, kind=Goal.Kind.PAYOFF, target_amount=Decimal(0),
                 account=cuenta, baseline_amount=Decimal("48000"))
    _abonar(scoped, cuenta, 18000, _hace(1))

    assert meta.current == 30000          # lo que sigues debiendo
    assert meta.progress == pytest.approx(18000 / 48000)


@pytest.mark.django_db
def test_abonar_puntual_y_seguir_cargando_no_es_avanzar(scoped):
    """El caso que los abonos esconden: pagas cada mes y no debes menos."""
    cuenta = _deuda(scoped, 48000)
    meta = _meta(scoped, kind=Goal.Kind.PAYOFF, target_amount=Decimal(0),
                 account=cuenta, baseline_amount=Decimal("48000"))
    for mes in range(1, 7):
        _abonar(scoped, cuenta, 5000, _hace(mes))       # abonas 30.000
        _abonar(scoped, cuenta, -6000, _hace(mes))      # y cargas 36.000

    assert meta.current == 54000          # debes más que al empezar
    assert meta.progress == 0.0
    assert meta.pace is None              # no hay ritmo: no hay proyección


@pytest.mark.django_db
def test_deber_mas_que_al_empezar_salta_como_hueco(scoped):
    cuenta = _deuda(scoped, 20000)
    _meta(scoped, name="Libre de la tarjeta", kind=Goal.Kind.PAYOFF,
          target_amount=Decimal(0), account=cuenta,
          baseline_amount=Decimal("10000"))

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "goals.debt_growing")
    assert "debes más que cuando empezaste" in hallazgo.title
    assert hallazgo.severity == "high"


# --- El ritmo ---------------------------------------------------------------


@pytest.mark.django_db
def test_el_ritmo_sale_de_lo_que_apartaste_los_ultimos_meses(scoped):
    meta = _meta(scoped)
    _aportar(scoped, meta, 6, 5000, cada_mes_desde=5)

    assert meta.pace == 5000


@pytest.mark.django_db
def test_lo_viejo_no_infla_el_ritmo_de_ahora(scoped):
    """Si dejaste de apartar hace medio año, el ritmo de hoy es cero."""
    meta = _meta(scoped)
    _aportar(scoped, meta, 6, 10000, cada_mes_desde=12)      # y nada después

    assert meta.pace is None


@pytest.mark.django_db
def test_sin_historial_no_se_inventa_un_ritmo(scoped):
    """Una fecha sacada de dos semanas de datos es peor que ninguna fecha."""
    meta = _meta(scoped, started_on=HOY)
    GoalContribution.objects.create(household=scoped, goal=meta, date=HOY,
                                    amount=Decimal("5000"))

    assert meta.pace is None
    assert meta.eta is None


# --- La proyección ----------------------------------------------------------


@pytest.mark.django_db
def test_dice_cuando_llegarias_a_este_ritmo(scoped):
    meta = _meta(scoped, target_amount=Decimal("100000"))
    _aportar(scoped, meta, 6, 5000, cada_mes_desde=5)   # 30.000 apartados

    # Faltan 70.000 a 5.000 al mes: catorce meses.
    assert meta.pace == 5000
    meses = (meta.eta.year - HOY.year) * 12 + (meta.eta.month - HOY.month)
    assert meses == 14


@pytest.mark.django_db
def test_dice_cuantos_meses_tarde_llegarias(scoped):
    meta = _meta(scoped, target_amount=Decimal("100000"),
                 target_on=_hace(-6))                  # la querías en 6 meses
    _aportar(scoped, meta, 6, 5000, cada_mes_desde=5)

    assert meta.months_late == 8                       # 14 meses contra 6


@pytest.mark.django_db
def test_llegar_antes_de_tiempo_da_retraso_negativo(scoped):
    meta = _meta(scoped, target_amount=Decimal("100000"),
                 target_on=_hace(-36))
    _aportar(scoped, meta, 6, 10000, cada_mes_desde=5)

    assert meta.months_late < 0


@pytest.mark.django_db
def test_dice_cuanto_habria_que_apartar_para_llegar_a_tiempo(scoped):
    meta = _meta(scoped, target_amount=Decimal("120000"), target_on=_hace(-12))

    assert meta.monthly_needed == 10000


@pytest.mark.django_db
def test_el_hueco_es_lo_que_le_falta_a_tu_ritmo(scoped):
    meta = _meta(scoped, target_amount=Decimal("120000"), target_on=_hace(-12))
    _aportar(scoped, meta, 6, 4000, cada_mes_desde=5)

    # Hacen falta (120.000-24.000)/12 = 8.000 y llevas 4.000.
    assert meta.monthly_needed == 8000
    assert meta.pace == 4000
    assert meta.gap == 4000


@pytest.mark.django_db
def test_sin_fecha_hay_progreso_pero_no_hay_retraso(scoped):
    meta = _meta(scoped, target_on=None)
    _aportar(scoped, meta, 6, 5000, cada_mes_desde=5)

    assert meta.progress > 0
    assert meta.months_late is None
    assert meta.monthly_needed is None


# --- Lo que el sistema dice por su cuenta -----------------------------------


@pytest.mark.django_db
def test_avisa_de_la_meta_que_no_llega_a_tiempo(scoped):
    meta = _meta(scoped, name="Enganche de la casa",
                 target_amount=Decimal("100000"), target_on=_hace(-6))
    _aportar(scoped, meta, 6, 5000, cada_mes_desde=5)

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "goals.behind")
    assert "8 meses tarde" in hallazgo.title
    assert "al mes para llegar a tiempo" in hallazgo.detail
    assert hallazgo.severity == "high"          # más de medio año de retraso


@pytest.mark.django_db
def test_la_que_llega_a_tiempo_no_molesta(scoped):
    meta = _meta(scoped, target_amount=Decimal("100000"), target_on=_hace(-36))
    _aportar(scoped, meta, 6, 10000, cada_mes_desde=5)

    assert not [f for f in checks.run_all(scoped) if f.check == "goals.behind"]


@pytest.mark.django_db
def test_avisa_de_la_meta_que_lleva_meses_parada(scoped):
    """Casi siempre significa que ya no importa y lo que toca es cerrarla."""
    meta = _meta(scoped)
    _aportar(scoped, meta, 2, 5000, cada_mes_desde=8)

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "goals.stalled")
    assert "sin moverse" in hallazgo.title


@pytest.mark.django_db
def test_avisa_de_la_meta_que_nunca_arranco(scoped):
    _meta(scoped, name="Viaje", target_on=_hace(-10))

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "goals.no_pace")
    assert "no ha arrancado" in hallazgo.title


@pytest.mark.django_db
def test_avisa_de_la_meta_cumplida_para_cerrarla(scoped):
    meta = _meta(scoped, target_amount=Decimal("10000"))
    _aportar(scoped, meta, 1, 12000)

    hallazgo = next(f for f in checks.run_all(scoped) if f.check == "goals.reached")
    assert "llegaste" in hallazgo.title


@pytest.mark.django_db
def test_una_meta_cerrada_deja_de_contar(scoped):
    meta = _meta(scoped, is_active=False, target_on=_hace(-1))

    assert not [f for f in checks.run_all(scoped) if f.subject_id == meta.pk]


# --- Apartar de verdad ------------------------------------------------------


@pytest.mark.django_db
def test_apartar_para_una_meta_sube_la_provision(scoped):
    """Atarla a una provisión es lo que hace que el dinero deje de estar libre."""
    from lares.modules.finance.models_provision import Provision
    from lares.modules.goals.forms import ContributionForm

    cuenta = Account.objects.create(household=scoped, name="Nómina",
                                    type=Account.Type.ASSET)
    provision = Provision.objects.create(household=scoped, name="Enganche",
                                         account=cuenta,
                                         target_amount=Decimal("100000"))
    meta = _meta(scoped, provision=provision)

    form = ContributionForm({"date": HOY, "amount": "5000", "note": ""},
                            goal=meta, household=scoped)
    assert form.is_valid(), form.errors
    form.save()

    provision.refresh_from_db()
    assert provision.saved_amount == 5000


@pytest.mark.django_db
def test_apartar_entre_dos_cuentas_deja_asiento(scoped):
    """Apartar sin que el libro se entere deja el disponible real inflado."""
    from lares.modules.goals.forms import ContributionForm

    origen = Account.objects.create(household=scoped, name="Nómina",
                                    type=Account.Type.ASSET)
    destino = Account.objects.create(household=scoped, name="Ahorro",
                                     type=Account.Type.ASSET)
    meta = _meta(scoped, account=destino)

    form = ContributionForm(
        {"date": HOY, "amount": "5000", "note": "",
         "account": str(origen.pk), "destination": str(destino.pk)},
        goal=meta, household=scoped)
    assert form.is_valid(), form.errors
    aporte = form.save()

    assert aporte.entry is not None
    assert origen.balance == -5000
    assert destino.balance == 5000


@pytest.mark.django_db
def test_una_deuda_sin_cuenta_no_se_puede_guardar(scoped):
    """Sin saldo que leer, el avance tendría que salir de los abonos."""
    from lares.modules.goals.forms import GoalForm

    form = GoalForm({"name": "Tarjeta", "kind": Goal.Kind.PAYOFF,
                     "target_amount": "0", "currency": "MXN",
                     "started_on": HOY, "baseline_amount": "10000",
                     "is_active": True}, household=scoped)

    assert not form.is_valid()
    assert "account" in form.errors


# --- Pantallas --------------------------------------------------------------


@pytest.mark.django_db
def test_las_pantallas_de_metas_abren(sesion_admin, household):
    meta = _meta(household)

    for url in ("/metas/", "/metas/nueva/", f"/metas/{meta.pk}/",
                f"/metas/{meta.pk}/editar/", f"/metas/{meta.pk}/apartar/"):
        assert sesion_admin.get(url).status_code == 200, url


@pytest.mark.django_db
def test_cerrar_una_meta_la_saca_de_la_lista(sesion_admin, household):
    meta = _meta(household)
    sesion_admin.get(f"/metas/{meta.pk}/cerrar/")

    meta.refresh_from_db()
    assert not meta.is_active
