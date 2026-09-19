"""Pagos recurrentes.

Netflix es una suscripción, el agua es un servicio del inmueble y la colegiatura
es una regla que escribe el usuario. Son tres modelos distintos a propósito —una
suscripción se cancela por una URL, un servicio cuelga de una casa y tiene número
de contrato— pero para la única pregunta que importa, *cuánto me cobran al mes*,
son lo mismo, y ningún módulo puede contestarla solo.

Lo que se prueba es que se suman bien aunque cobren cada tanto distinto, que lo
de importe desconocido no se cuela en el total como si fuera cero, y que el
sistema avisa cuando la misma cosa acaba registrada dos veces.
"""

import datetime as dt
from decimal import Decimal

import pytest

from lares.core.models import ObligationRule, Party
from lares.core.registry import registry
from lares.core.services import checks
from lares.core.views_crud import _ciclo_de, _reglas_propias
from lares.modules.property.models import Property, Service
from lares.modules.subscriptions.models import Subscription

HOY = dt.date.today()


def _sub(household, **kwargs):
    datos = dict(kind="subscription", name="Netflix", currency="MXN",
                 amount=Decimal("219"), cycle=Subscription.Cycle.MONTHLY)
    datos.update(kwargs)
    return Subscription.objects.create(household=household, **datos)


def _servicio(household, **kwargs):
    inmueble = Property.objects.create(household=household, kind="property",
                                       name="Casa", currency="MXN")
    datos = dict(kind="service", name="Agua", property_ref=inmueble,
                 service_kind=Service.Kind.WATER, cycle=Service.Cycle.BIMONTHLY,
                 typical_amount=Decimal("640"), currency="MXN")
    datos.update(kwargs)
    return Service.objects.create(household=household, **datos)


def _regla(household, **kwargs):
    datos = dict(key="colegiatura", label="Colegiatura",
                 schedule={"monthly": {"day": 10}}, amount=Decimal("4500"),
                 currency="MXN")
    datos.update(kwargs)
    return ObligationRule.objects.create(household=household, **datos)


def _todo(household):
    return registry.recurring_all(household) + _reglas_propias(household)


def _por_titulo(household):
    return {r.title: r for r in _todo(household)}


# --- Todo lo que cobra aparece junto ----------------------------------------


@pytest.mark.django_db
def test_una_suscripcion_y_un_servicio_salen_en_la_misma_lista(scoped):
    """Era el hueco: «Recurrentes» solo mostraba las reglas escritas a mano."""
    _sub(scoped)
    _servicio(scoped)
    _regla(scoped)

    titulos = _por_titulo(scoped)
    assert "Netflix" in titulos
    assert "Agua · Casa" in titulos
    assert "Colegiatura" in titulos


@pytest.mark.django_db
def test_cada_uno_dice_de_donde_viene(scoped):
    """Para poder ir a administrarlo donde de verdad vive."""
    _sub(scoped)
    _servicio(scoped)
    _regla(scoped)

    fuentes = {r.title: r.source for r in _todo(scoped)}
    assert fuentes["Netflix"] == "subscriptions"
    assert fuentes["Agua · Casa"] == "property"
    assert fuentes["Colegiatura"] == "core"


@pytest.mark.django_db
def test_lo_cancelado_deja_de_contar(scoped):
    _sub(scoped, status=Subscription.Status.DISPOSED)

    assert "Netflix" not in _por_titulo(scoped)


# --- Ciclos distintos, una sola cifra ---------------------------------------


@pytest.mark.django_db
def test_lo_anual_y_lo_bimestral_se_normalizan_al_mes(scoped):
    """Sumar un seguro anual con un streaming mensual sin traducir daría 0."""
    _sub(scoped, name="VPS", amount=Decimal("1200"),
         cycle=Subscription.Cycle.YEARLY)
    _servicio(scoped)                        # 640 cada dos meses

    titulos = _por_titulo(scoped)
    assert titulos["VPS"].per_month == 100
    assert titulos["VPS"].per_year == 1200
    assert titulos["Agua · Casa"].per_month == 320


@pytest.mark.django_db
def test_una_regla_cada_tres_meses_se_lee_como_trimestral(scoped):
    regla = _regla(scoped, key="predial",
                   schedule={"every": {"months": 3}, "from": "2026-01-15"})

    assert _ciclo_de(regla) == "quarterly"
    assert _por_titulo(scoped)["Colegiatura"].per_month == 1500


@pytest.mark.django_db
def test_lo_que_pasa_una_sola_vez_no_es_recurrente(scoped):
    """Una regla de fecha única no cuenta en lo que te cuesta cada mes."""
    regla = _regla(scoped, key="unica", label="Tenencia",
                   schedule={"on_date": "2026-03-31"})

    assert _ciclo_de(regla) is None
    assert "Tenencia" not in _por_titulo(scoped)


# --- Lo que no se sabe no se inventa ----------------------------------------


@pytest.mark.django_db
def test_un_importe_desconocido_no_cuenta_como_cero(scoped):
    """Decir que el total es exacto cuando falta el recibo del gas engaña."""
    _servicio(scoped, typical_amount=None)

    partida = _por_titulo(scoped)["Agua · Casa"]
    assert partida.per_month is None
    assert partida.note == "importe variable"


@pytest.mark.django_db
def test_la_pantalla_avisa_de_lo_que_no_entra_en_la_suma(sesion_admin, household):
    _servicio(household, typical_amount=None)
    _sub(household)

    contexto = sesion_admin.get("/recurrentes/").context
    assert len(contexto["sin_importe"]) == 1
    assert contexto["al_mes"] == 219          # solo lo que sí se sabe
    assert "sin importe conocido" in sesion_admin.get("/recurrentes/") \
        .content.decode()


# --- La misma cosa dos veces ------------------------------------------------


@pytest.mark.django_db
def test_avisa_si_una_regla_repite_un_servicio_ya_registrado(scoped):
    """Registras el agua en la casa y meses después programas su recibo.

    Nada falla: salen dos avisos y el gasto del mes sale al doble.
    """
    _servicio(scoped)
    _regla(scoped, key="agua", label="Recibo de agua",
           schedule={"every": {"months": 2}})

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "core.duplicate_recurring")
    assert "Recibo de agua" in hallazgo.title
    assert "Agua · Casa" in hallazgo.title


@pytest.mark.django_db
def test_la_misma_contraparte_basta_para_sospechar(scoped):
    siapa = Party.objects.create(household=scoped, name="SIAPA",
                                 kind=Party.Kind.ORGANIZATION)
    _servicio(scoped, provider=siapa)
    _regla(scoped, key="h2o", label="Consumo bimestral", counterparty=siapa,
           schedule={"every": {"months": 2}})

    assert [f for f in checks.run_all(scoped)
            if f.check == "core.duplicate_recurring"]


@pytest.mark.django_db
def test_un_nombre_propio_compartido_no_es_un_duplicado(scoped):
    """«Clases de piano de Diego» y «iCloud de Diego» no son lo mismo.

    Una alerta falsa en la pantalla que existe para detectar huecos le quita
    el valor a todas las demás.
    """
    Party.objects.create(household=scoped, name="Diego", kind=Party.Kind.PERSON)
    _sub(scoped, name="iCloud de Diego", amount=Decimal("49"))
    _regla(scoped, key="piano", label="Clases de piano de Diego")

    assert not [f for f in checks.run_all(scoped)
                if f.check == "core.duplicate_recurring"]


@pytest.mark.django_db
def test_dos_recurrentes_distintos_no_se_acusan(scoped):
    _sub(scoped)
    _regla(scoped)

    assert not [f for f in checks.run_all(scoped)
                if f.check == "core.duplicate_recurring"]


@pytest.mark.django_db
def test_una_regla_pausada_no_se_acusa_de_duplicar(scoped):
    _servicio(scoped)
    _regla(scoped, key="agua", label="Recibo de agua", is_active=False,
           schedule={"every": {"months": 2}})

    assert not [f for f in checks.run_all(scoped)
                if f.check == "core.duplicate_recurring"]


# --- La pantalla ------------------------------------------------------------


@pytest.mark.django_db
def test_la_pantalla_agrupa_por_origen_y_suma(sesion_admin, household):
    _sub(household)                                   # 219 al mes
    _servicio(household)                              # 640 cada dos meses
    _regla(household)                                 # 4.500 al mes

    contexto = sesion_admin.get("/recurrentes/").context
    assert contexto["al_mes"] == 219 + 320 + 4500
    assert contexto["al_ano"] == contexto["al_mes"] * 12
    assert contexto["cuantos"] == 3
    titulos = [t for t, _ in contexto["grupos"]]
    assert "Suscripciones" in titulos
    assert "Servicios del inmueble" in titulos
    assert "Lo que programaste tú" in titulos


@pytest.mark.django_db
def test_la_pantalla_abre_sin_nada_registrado(sesion_admin, household):
    respuesta = sesion_admin.get("/recurrentes/")

    assert respuesta.status_code == 200
    assert "Nada que se repita" in respuesta.content.decode()


@pytest.mark.django_db
def test_un_proveedor_roto_no_tumba_la_pantalla(sesion_admin, household):
    def revienta(_):
        raise RuntimeError("módulo roto")

    registry.recurring_providers.append(revienta)
    try:
        assert sesion_admin.get("/recurrentes/").status_code == 200
    finally:
        registry.recurring_providers.remove(revienta)


@pytest.mark.django_db
def test_una_regla_pausada_sigue_visible_pero_no_suma(sesion_admin, household):
    """Si desapareciera no habría desde dónde reanudarla."""
    _regla(household, is_active=False)
    _sub(household)

    contexto = sesion_admin.get("/recurrentes/").context
    assert contexto["al_mes"] == 219
    assert contexto["cuantos"] == 1
    titulos = [r.title for _, filas in contexto["grupos"] for r in filas]
    assert "Colegiatura" in titulos


@pytest.mark.django_db
def test_solo_las_reglas_propias_se_pausan_desde_aqui(sesion_admin, household):
    """Una suscripción se da de baja en su ficha, donde está cómo cancelarla."""
    _regla(household)
    _sub(household)

    filas = {r.title: r for _, g in
             sesion_admin.get("/recurrentes/").context["grupos"] for r in g}
    assert filas["Colegiatura"].pk is not None
    assert filas["Netflix"].pk is None
