"""Exportar e importar: la prueba de que los datos son del usuario.

Un export que no se puede volver a cargar no es portabilidad, es un archivo.
Por eso la prueba central borra el hogar de verdad antes de restaurarlo.
"""

import datetime as dt

import pytest

from lares.core.models import Account, Document, Household, Obligation, Party
from lares.core.services import obligations, portability
from lares.modules.finance.models import CreditCard
from lares.modules.tasks.models import Task
from lares.modules.vehicles.models import Vehicle

HOY = dt.date(2026, 9, 18)


@pytest.fixture
def hogar_poblado(scoped, me):
    Vehicle.objects.create(
        household=scoped, name="Mazda CX-5", kind="vehicle",
        plates="JGT1234", owner=me, current_value=410000,
    )
    cuenta = Account.objects.create(
        household=scoped, name="Tarjeta", type=Account.Type.LIABILITY
    )
    CreditCard.objects.create(
        household=scoped, name="Tarjeta BBVA", kind="credit_card",
        account=cuenta, last_four="1234", due_day=5,
    )
    Document.objects.create(
        household=scoped, title="Pasaporte", doc_type="passport",
        expires_on=dt.date(2027, 5, 16),
    )
    Task.objects.create(household=scoped, title="Cotizar seguro")
    obligations.materialize(scoped, HOY)
    return scoped


@pytest.mark.django_db
def test_exporta_tambien_lo_que_aportan_los_modulos(hogar_poblado, tmp_path):
    ruta = portability.export_household(hogar_poblado, tmp_path / "export.zip")
    assert ruta.exists()

    import json
    import zipfile
    with zipfile.ZipFile(ruta) as zf:
        manifest = json.loads(zf.read("manifest.json"))

    modelos = {e["model"] for e in manifest["models"]}
    # El nucleo no conoce estos modelos y aun asi salen en el export.
    assert {"vehicles.vehicle", "finance.creditcard", "tasks.task"} <= modelos
    assert manifest["format"] == portability.FORMAT


@pytest.mark.django_db
def test_el_padre_va_antes_que_la_hija_en_el_orden_de_carga(hogar_poblado, tmp_path):
    orden = [m._meta.label_lower for m in portability.exportable_models()]
    assert orden.index("core.resource") < orden.index("vehicles.vehicle")
    assert orden.index("core.entry") < orden.index("core.posting")
    assert orden.index("core.household") < orden.index("core.party")


@pytest.mark.django_db
def test_borrar_el_hogar_y_restaurarlo_lo_deja_igual(hogar_poblado, tmp_path):
    antes = {
        "vehiculos": Vehicle.objects.count(),
        "tarjetas": CreditCard.objects.count(),
        "documentos": Document.objects.count(),
        "tareas": Task.objects.count(),
        "obligaciones": Obligation.objects.count(),
        "partes": Party.objects.count(),
    }
    assert all(v > 0 for v in antes.values())

    ruta = portability.export_household(hogar_poblado, tmp_path / "export.zip")
    slug = hogar_poblado.slug
    Household.objects.filter(pk=hogar_poblado.pk).delete()
    assert not Household.objects.filter(slug=slug).exists()

    result = portability.import_household(ruta)
    assert result["household"]["slug"] == slug

    restaurado = Household.objects.get(slug=slug)
    from lares.core.scoping import use_household
    with use_household(restaurado):
        despues = {
            "vehiculos": Vehicle.objects.count(),
            "tarjetas": CreditCard.objects.count(),
            "documentos": Document.objects.count(),
            "tareas": Task.objects.count(),
            "obligaciones": Obligation.objects.count(),
            "partes": Party.objects.count(),
        }
    assert despues == antes


@pytest.mark.django_db
def test_rechaza_un_formato_que_no_conoce(hogar_poblado, tmp_path):
    import json
    import zipfile

    ruta = tmp_path / "raro.zip"
    with zipfile.ZipFile(ruta, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "otra-cosa/9"}))

    with pytest.raises(ValueError, match="Formato desconocido"):
        portability.import_household(ruta)
