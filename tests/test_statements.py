"""Importar estados de cuenta.

La regla que sostiene todo: importar dos veces el mismo archivo no debe crear
nada dos veces. Un libro con movimientos duplicados no se puede conciliar, y
entonces deja de servir para lo único que sirve un libro.
"""

import datetime as dt
import pathlib
from decimal import Decimal

import pytest

from lares.core.models import Account, Entry, Posting
from lares.modules.finance import importing, statements

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CSV = (FIXTURES / "estado_bbva.csv").read_bytes()
OFX = (FIXTURES / "estado.ofx").read_bytes()


@pytest.fixture
def cuentas(scoped):
    return {
        "banco": Account.objects.create(household=scoped, name="Nómina",
                                        type=Account.Type.ASSET, currency="MXN"),
        "gasto": Account.objects.create(household=scoped, name="Gastos",
                                        type=Account.Type.EXPENSE),
    }


# --- Lectura de importes y fechas -------------------------------------------


@pytest.mark.parametrize("texto,esperado", [
    ("1,234.56", Decimal("1234.56")),        # formato inglés
    ("1.234,56", Decimal("1234.56")),        # formato español
    ("$ 980.00", Decimal("980.00")),
    ("(123.45)", Decimal("-123.45")),        # negativo entre paréntesis
    ("-1.420,00", Decimal("-1420.00")),
    ("42000", Decimal("42000")),
    ("", None),
])
def test_lee_los_importes_de_cualquier_banco(texto, esperado):
    assert statements.parse_amount(texto) == esperado


@pytest.mark.parametrize("texto,esperado", [
    ("2026-09-12", dt.date(2026, 9, 12)),
    ("12/09/2026", dt.date(2026, 9, 12)),
    ("20260912120000", dt.date(2026, 9, 12)),
    ("no es fecha", None),
])
def test_lee_las_fechas_de_cualquier_banco(texto, esperado):
    assert statements.parse_date(texto) == esperado


# --- CSV --------------------------------------------------------------------


def test_lee_un_csv_con_cargo_y_abono_en_columnas_distintas():
    movimientos, cabeceras, mapa = statements.read_csv(CSV)

    assert len(movimientos) == 4
    assert movimientos[0].description == "GASOLINERA PEMEX AMERICAS"
    assert movimientos[0].amount == Decimal("-980.00")      # cargo, en negativo
    assert movimientos[2].amount == Decimal("42000.00")     # abono, en positivo


def test_adivina_las_columnas_por_su_nombre():
    mapa = statements.sniff_columns(["Fecha", "Descripción", "Cargo", "Abono", "Saldo"])
    assert mapa["date"] == 0
    assert mapa["description"] == 1
    assert mapa["debit"] == 2
    assert mapa["credit"] == 3


def test_las_filas_sin_fecha_se_ignoran():
    basura = b"Fecha;Concepto;Importe\n;Total del periodo;99999\n"
    movimientos, _, _ = statements.read_csv(basura)
    assert movimientos == []


# --- OFX --------------------------------------------------------------------


def test_lee_un_ofx_sgml_aunque_no_cierre_etiquetas():
    """El OFX 1.x no es XML: un parser de XML se atraganta con él."""
    movimientos = statements.read_ofx(OFX)

    assert len(movimientos) == 2
    assert movimientos[0].amount == Decimal("-980.00")
    assert movimientos[0].description == "GASOLINERA PEMEX"


def test_el_ofx_trae_el_identificador_del_banco():
    """Con FITID, deduplicar deja de ser una heurística."""
    movimientos = statements.read_ofx(OFX)
    assert movimientos[0].external_ref == "2026091200123"
    assert movimientos[0].fingerprint == "2026091200123"


def test_elige_el_lector_por_el_contenido_no_por_la_extension():
    movimientos, _, _ = statements.read(OFX, nombre="descarga.txt")
    assert len(movimientos) == 2


# --- Huella de un movimiento ------------------------------------------------


def test_dos_movimientos_iguales_tienen_la_misma_huella():
    a = statements.Movement(dt.date(2026, 9, 12), "  PEMEX  ", Decimal("-980"))
    b = statements.Movement(dt.date(2026, 9, 12), "pemex", Decimal("-980"))
    assert a.fingerprint == b.fingerprint


def test_cambiar_el_importe_cambia_la_huella():
    a = statements.Movement(dt.date(2026, 9, 12), "PEMEX", Decimal("-980"))
    b = statements.Movement(dt.date(2026, 9, 12), "PEMEX", Decimal("-981"))
    assert a.fingerprint != b.fingerprint


# --- Conciliación -----------------------------------------------------------


@pytest.mark.django_db
def test_lo_que_no_existe_se_propone_como_nuevo(scoped, cuentas):
    movimientos, _, _ = statements.read_csv(CSV)
    filas = importing.reconcile(scoped, cuentas["banco"], movimientos)

    assert all(f.status == "new" for f in filas)


@pytest.mark.django_db
def test_importar_dos_veces_no_duplica(scoped, cuentas):
    """La regla que sostiene todo lo demás."""
    movimientos, _, _ = statements.read_csv(CSV)
    filas = importing.reconcile(scoped, cuentas["banco"], movimientos)
    importing.apply(scoped, cuentas["banco"], cuentas["gasto"], filas)
    assert Entry.objects.count() == 4

    otra_vez = importing.reconcile(scoped, cuentas["banco"], movimientos)
    resultado = importing.apply(scoped, cuentas["banco"], cuentas["gasto"], otra_vez)

    assert Entry.objects.count() == 4
    assert resultado["created"] == 0
    assert resultado["known"] == 4


@pytest.mark.django_db
def test_lo_que_ya_apuntaste_a_mano_se_enlaza_en_vez_de_duplicarse(scoped, cuentas):
    """Registraste «Gasolina» el martes; el banco lo reporta el jueves."""
    entry = Entry.objects.create(household=scoped, date=dt.date(2026, 9, 10),
                                 description="Gasolina del Mazda")
    Posting.objects.create(household=scoped, entry=entry, account=cuentas["gasto"],
                           amount=Decimal("980"))
    Posting.objects.create(household=scoped, entry=entry, account=cuentas["banco"],
                           amount=Decimal("-980"))

    movimientos, _, _ = statements.read_csv(CSV)
    filas = importing.reconcile(scoped, cuentas["banco"], movimientos)
    encajado = [f for f in filas if f.status == "match"]

    assert len(encajado) == 1
    assert encajado[0].entry.pk == entry.pk

    resultado = importing.apply(scoped, cuentas["banco"], cuentas["gasto"], filas)
    assert resultado["linked"] == 1
    assert Entry.objects.count() == 4       # los 3 nuevos + el que ya estaba


@pytest.mark.django_db
def test_un_encaje_deja_marcada_la_referencia_del_banco(scoped, cuentas):
    entry = Entry.objects.create(household=scoped, date=dt.date(2026, 9, 12),
                                 description="Gasolina")
    Posting.objects.create(household=scoped, entry=entry, account=cuentas["banco"],
                           amount=Decimal("-980"))

    movimientos, _, _ = statements.read_csv(CSV)
    filas = importing.reconcile(scoped, cuentas["banco"], movimientos)
    importing.apply(scoped, cuentas["banco"], cuentas["gasto"], filas)

    entry.refresh_from_db()
    assert entry.external_ref        # la próxima vez se reconoce sin heurísticas


@pytest.mark.django_db
def test_un_importe_distinto_no_se_da_por_encajado(scoped, cuentas):
    entry = Entry.objects.create(household=scoped, date=dt.date(2026, 9, 12),
                                 description="Otra cosa")
    Posting.objects.create(household=scoped, entry=entry, account=cuentas["banco"],
                           amount=Decimal("-500"))

    movimientos, _, _ = statements.read_csv(CSV)
    filas = importing.reconcile(scoped, cuentas["banco"], movimientos)
    assert all(f.status == "new" for f in filas)


@pytest.mark.django_db
def test_los_asientos_creados_cuadran_en_cero(scoped, cuentas):
    movimientos, _, _ = statements.read_csv(CSV)
    filas = importing.reconcile(scoped, cuentas["banco"], movimientos)
    importing.apply(scoped, cuentas["banco"], cuentas["gasto"], filas)

    for entry in Entry.objects.all():
        assert entry.is_balanced


@pytest.mark.django_db
def test_el_saldo_de_la_cuenta_refleja_lo_importado(scoped, cuentas):
    movimientos, _, _ = statements.read_csv(CSV)
    filas = importing.reconcile(scoped, cuentas["banco"], movimientos)
    importing.apply(scoped, cuentas["banco"], cuentas["gasto"], filas)

    # −980 −2340 +42000 −1420
    assert cuentas["banco"].balance == Decimal("37260.00")


@pytest.mark.django_db
def test_lo_sin_clasificar_va_a_una_cuenta_visible(scoped, cuentas):
    """Mejor un «Sin clasificar» a la vista que inventar una categoría."""
    cuenta = importing.default_category(scoped, Decimal("-1"))
    assert cuenta.name == "Sin clasificar"
    assert cuenta.type == Account.Type.EXPENSE
