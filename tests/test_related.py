"""Enlaces de una ficha (los «smart buttons»).

Entrar en una ficha tiene que servir para llegar al resto: en BBVA quieres ver
sus cuentas; en Diego, si le prestaste la guitarra.
"""

import datetime as dt

import pytest

from lares.core import related
from lares.core.models import Account, Entry, Party, Posting
from lares.core.registry import registry
from lares.modules.belongings.models import Belonging

HOY = dt.date.today()


@pytest.fixture
def diego(scoped):
    return Party.objects.create(household=scoped, name="Diego")


@pytest.fixture
def guitarra(scoped, me):
    return Belonging.objects.create(
        household=scoped, name="Guitarra Martin D-28", kind="belonging",
        category=Belonging.Category.INSTRUMENT, owner=me, current_value=52000,
    )


def _enlaces(party) -> dict:
    return {e.label: e for e in registry.links_for(party)}


# --- Préstamos de objetos ---------------------------------------------------


@pytest.mark.django_db
def test_prestar_algo_aparece_en_la_ficha_de_quien_lo_tiene(sesion_admin, scoped,
                                                            diego, guitarra):
    sesion_admin.post(f"/r/{guitarra.pk}/prestar/", {"party": str(diego.pk)})

    assert [r.name for r in related.lent_to(diego)] == ["Guitarra Martin D-28"]
    assert str(related.borrower_of(guitarra)) == "Diego"
    assert "cosa que le prestaste" in _enlaces(diego)


@pytest.mark.django_db
def test_devolver_cierra_el_prestamo_sin_borrar_el_historial(sesion_admin, scoped,
                                                             diego, guitarra):
    from lares.core.models import Link

    sesion_admin.post(f"/r/{guitarra.pk}/prestar/", {"party": str(diego.pk)})
    sesion_admin.post(f"/r/{guitarra.pk}/devolver/")

    assert related.lent_to(diego) == []
    assert related.borrower_of(guitarra) is None
    # La arista sigue ahí, cerrada: el préstamo pasado es historial.
    assert Link.objects.filter(role=related.LENT_TO, valid_to__isnull=False).exists()


# --- Lo que cuelga de una parte ---------------------------------------------


@pytest.mark.django_db
def test_una_institucion_ensena_sus_cuentas(scoped):
    bbva = Party.objects.create(household=scoped, name="BBVA",
                                kind=Party.Kind.ORGANIZATION)
    Account.objects.create(household=scoped, name="Nómina", type=Account.Type.ASSET,
                           institution=bbva)
    Account.objects.create(household=scoped, name="Tarjeta",
                           type=Account.Type.LIABILITY, institution=bbva)

    assert _enlaces(bbva)["cuentas"].count == 2


@pytest.mark.django_db
def test_un_comercio_ensena_cuanto_llevas_gastado(scoped):
    walmart = Party.objects.create(household=scoped, name="Walmart",
                                   kind=Party.Kind.ORGANIZATION)
    tarjeta = Account.objects.create(household=scoped, name="Tarjeta",
                                     type=Account.Type.LIABILITY)
    super_ = Account.objects.create(household=scoped, name="Súper",
                                    type=Account.Type.EXPENSE)
    for importe in (2340, 1980):
        e = Entry.objects.create(household=scoped, date=HOY, description="Despensa",
                                 counterparty=walmart)
        Posting.objects.create(household=scoped, entry=e, account=super_, amount=importe)
        Posting.objects.create(household=scoped, entry=e, account=tarjeta, amount=-importe)

    enlace = _enlaces(walmart)["movimientos"]
    assert enlace.count == 2
    assert "$4,320" in enlace.hint            # con símbolo y separadores


@pytest.mark.django_db
def test_una_persona_ensena_cuanto_gastaste_en_ella(scoped, diego):
    tarjeta = Account.objects.create(household=scoped, name="Tarjeta",
                                     type=Account.Type.LIABILITY)
    familia = Account.objects.create(household=scoped, name="Familia",
                                     type=Account.Type.EXPENSE)
    e = Entry.objects.create(household=scoped, date=HOY, description="Mesada")
    Posting.objects.create(household=scoped, entry=e, account=familia, amount=1500,
                           beneficiary=diego)
    Posting.objects.create(household=scoped, entry=e, account=tarjeta, amount=-1500)

    assert "$1,500" in _enlaces(diego)["gastado en esta persona"].hint


@pytest.mark.django_db
def test_un_proveedor_ensena_sus_trabajos_y_lo_pagado(scoped, me):
    from django.contrib.contenttypes.models import ContentType

    from lares.modules.maintenance.models import WorkOrder
    from lares.modules.vehicles.models import Vehicle

    taller = Party.objects.create(household=scoped, name="Taller",
                                  kind=Party.Kind.ORGANIZATION)
    coche = Vehicle.objects.create(household=scoped, name="Mazda", kind="vehicle",
                                   owner=me)
    for titulo, coste in (("Afinación", 4750), ("Balanceo", 890)):
        WorkOrder.objects.create(
            household=scoped, title=titulo, done_on=HOY, provider=taller, cost=coste,
            subject_type=ContentType.objects.get_for_model(Vehicle),
            subject_id=coche.pk,
        )

    enlace = _enlaces(taller)["trabajos hechos"]
    assert enlace.count == 2
    assert "$5,640" in enlace.hint


@pytest.mark.django_db
def test_una_parte_sin_nada_no_ensena_enlaces_vacios(scoped, diego):
    """Un «0 documentos» es ruido: si no hay nada, no se pinta."""
    assert registry.links_for(diego) == []
