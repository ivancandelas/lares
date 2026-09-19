"""Impuestos.

Este módulo **no presenta declaraciones ni calcula el ISR**, y buena parte de
estas pruebas existe para que siga siendo así. La línea está puesta donde la
aritmética deja de ser auditable:

  - la base gravable se calcula, porque es una resta que cualquiera comprueba;
  - el ISR con tarifa progresiva no, porque sus tablas cambian cada año y
    equivocarse tiene consecuencias legales;
  - RESICO es la excepción: su tasa es fija por tramo (art. 113-E LISR).

Lo demás que se prueba es lo que de verdad cuesta dinero cuando falla: deducir
la misma factura dos veces, pasarse del tope sin enterarse, y pagar un impuesto
que ya te retuvieron.
"""

import datetime as dt
import io
import zipfile
from decimal import Decimal

import pytest

from lares.core.models import Account, Document, Entry, Party, Posting
from lares.core.services import checks, obligations
from lares.modules.taxes.models import (
    Deduction,
    Filing,
    TaxProfile,
    Withholding,
)
from lares.modules.taxes.package import build
from lares.modules.taxes.services import resico_rate, summarize

HOY = dt.date.today()
ANO = HOY.year


def _perfil(household, **kwargs):
    quien = kwargs.pop("taxpayer", None) or Party.objects.create(
        household=household, name="Titular", kind=Party.Kind.PERSON)
    datos = dict(regime=TaxProfile.Regime.SALARIES, rfc="XAXX010101000")
    datos.update(kwargs)
    return TaxProfile.objects.create(household=household, taxpayer=quien, **datos)


def _ingreso(household, importe, cuando=None):
    """Un ingreso real, en partida doble."""
    banco, _ = Account.objects.get_or_create(
        household=household, name="Banco", defaults={"type": Account.Type.ASSET})
    sueldo, _ = Account.objects.get_or_create(
        household=household, name="Ingresos", defaults={"type": Account.Type.INCOME})
    entry = Entry.objects.create(household=household, description="Ingreso",
                                 date=cuando or dt.date(ANO, 6, 15))
    Posting.objects.create(household=household, entry=entry, account=banco,
                           amount=Decimal(importe), currency="MXN")
    Posting.objects.create(household=household, entry=entry, account=sueldo,
                           amount=-Decimal(importe), currency="MXN")


def _deducir(household, perfil, importe, **kwargs):
    datos = dict(kind=Deduction.Kind.MEDICAL, amount=Decimal(importe),
                 date=dt.date(ANO, 6, 1))
    datos.update(kwargs)
    return Deduction.objects.create(household=household, profile=perfil, **datos)


# --- Dónde está la línea ----------------------------------------------------


@pytest.mark.django_db
def test_la_base_se_calcula_pero_el_impuesto_no(scoped):
    """Restar es auditable; una tarifa progresiva que cambia cada año, no."""
    perfil = _perfil(scoped, regime=TaxProfile.Regime.BUSINESS)
    _ingreso(scoped, 500000)
    _deducir(scoped, perfil, 40000, kind=Deduction.Kind.BUSINESS)

    resumen = summarize(scoped, perfil, ANO)
    assert resumen.income == 500000
    assert resumen.base == 460000
    assert resumen.resico_estimate is None       # no hay cifra de impuesto


@pytest.mark.django_db
def test_resico_si_da_cifra_porque_su_tasa_es_fija(scoped):
    """Art. 113-E LISR: tasa por tramo de ingreso mensual, sin deducciones."""
    perfil = _perfil(scoped, regime=TaxProfile.Regime.RESICO)
    _ingreso(scoped, 240000)                     # 20.000 al mes → 1%

    assert summarize(scoped, perfil, ANO).resico_estimate == Decimal("2400.00")


@pytest.mark.django_db
@pytest.mark.parametrize("mensual,tasa", [
    (20000, "0.0100"), (25000, "0.0100"), (40000, "0.0110"),
    (60000, "0.0150"), (150000, "0.0200"), (250000, "0.0250"),
])
def test_los_tramos_de_resico(mensual, tasa):
    assert resico_rate(Decimal(mensual)) == Decimal(tasa)


@pytest.mark.django_db
def test_pasado_el_ultimo_tramo_resico_no_da_tasa(scoped):
    """Ahí ya no aplica el régimen, y dar la tasa más alta lo disimularía."""
    perfil = _perfil(scoped, regime=TaxProfile.Regime.RESICO)
    _ingreso(scoped, 6000000)                    # 500.000 al mes

    assert resico_rate(Decimal("500000")) is None
    assert summarize(scoped, perfil, ANO).resico_estimate is None


# --- Los ingresos salen del libro -------------------------------------------


@pytest.mark.django_db
def test_los_ingresos_salen_del_libro_no_de_las_facturas(scoped):
    """En persona física se declara lo cobrado, no lo facturado."""
    perfil = _perfil(scoped)
    _ingreso(scoped, 120000)
    Document.objects.create(household=scoped, title="Factura sin cobrar",
                            doc_type="invoice", amount=Decimal("80000"),
                            issued_on=dt.date(ANO, 5, 1))

    assert summarize(scoped, perfil, ANO).income == 120000


@pytest.mark.django_db
def test_lo_de_otro_ejercicio_no_entra(scoped):
    perfil = _perfil(scoped)
    _ingreso(scoped, 100000, cuando=dt.date(ANO - 1, 6, 1))
    _deducir(scoped, perfil, 5000, date=dt.date(ANO - 1, 6, 1))

    resumen = summarize(scoped, perfil, ANO)
    assert resumen.income == 0
    assert resumen.personal == 0


# --- La deducción ciega del arrendamiento -----------------------------------


@pytest.mark.django_db
def test_el_arrendamiento_deduce_el_35_por_ciento_sin_comprobar_nada(scoped):
    """Art. 115 LISR. Sale mejor que deducir gastos reales y casi nadie lo usa."""
    perfil = _perfil(scoped, regime=TaxProfile.Regime.LEASE)
    _ingreso(scoped, 200000)

    resumen = summarize(scoped, perfil, ANO)
    assert resumen.blind_deduction == 70000
    assert resumen.base == 130000


@pytest.mark.django_db
def test_los_demas_regimenes_no_tienen_deduccion_ciega(scoped):
    perfil = _perfil(scoped, regime=TaxProfile.Regime.BUSINESS)
    _ingreso(scoped, 200000)

    assert summarize(scoped, perfil, ANO).blind_deduction == 0


# --- El tope de las deducciones personales ----------------------------------


@pytest.mark.django_db
def test_las_personales_topan_al_quince_por_ciento(scoped):
    perfil = _perfil(scoped)
    _ingreso(scoped, 300000)
    _deducir(scoped, perfil, 80000)

    resumen = summarize(scoped, perfil, ANO)
    assert resumen.personal == 80000
    assert resumen.personal_allowed == 45000        # el 15%
    assert resumen.over_cap == 35000


@pytest.mark.django_db
def test_con_la_uma_capturada_manda_el_tope_menor(scoped):
    perfil = _perfil(scoped, uma_annual=Decimal("40000"))
    _ingreso(scoped, 1000000)                       # 15% = 150.000
    _deducir(scoped, perfil, 190000)

    # Cinco UMA son 200.000; el 15% son 150.000. Manda el menor.
    assert summarize(scoped, perfil, ANO).personal_allowed == 150000


@pytest.mark.django_db
def test_sin_la_uma_se_dice_que_el_tope_quedo_a_medias(scoped):
    """Callar que ese tope existe sería peor que no aplicarlo."""
    perfil = _perfil(scoped)
    _ingreso(scoped, 300000)
    _deducir(scoped, perfil, 10000)

    uma = next(c for c in summarize(scoped, perfil, ANO).caps
               if "UMA" in c.label)
    assert not uma.applied
    assert "no se aplicó" in uma.note


@pytest.mark.django_db
def test_lo_de_la_actividad_no_topa(scoped):
    """El tope es de las personales; un gasto del negocio es otra cosa."""
    perfil = _perfil(scoped, regime=TaxProfile.Regime.BUSINESS)
    _ingreso(scoped, 100000)
    _deducir(scoped, perfil, 90000, kind=Deduction.Kind.BUSINESS)

    resumen = summarize(scoped, perfil, ANO)
    assert resumen.business == 90000
    assert resumen.over_cap == 0
    assert resumen.base == 10000


@pytest.mark.django_db
def test_avisa_de_las_deducciones_que_no_van_a_contar(scoped):
    perfil = _perfil(scoped)
    _ingreso(scoped, 100000)
    _deducir(scoped, perfil, 60000)

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "taxes.over_cap")
    assert "45,000 de deducciones que no van a contar" in hallazgo.title


# --- La misma factura dos veces ---------------------------------------------


@pytest.mark.django_db
def test_una_factura_no_se_puede_deducir_dos_veces(scoped):
    """Es la forma más fácil de inflar una declaración sin darse cuenta."""
    from lares.modules.taxes.forms import DeductionForm

    perfil = _perfil(scoped)
    factura = Document.objects.create(household=scoped, title="Consulta",
                                      doc_type="invoice",
                                      amount=Decimal("3000"), issued_on=HOY)
    _deducir(scoped, perfil, 3000, document=factura)

    form = DeductionForm({"profile": str(perfil.pk), "kind": Deduction.Kind.MEDICAL,
                          "amount": "3000", "date": HOY,
                          "document": str(factura.pk)}, household=scoped)

    assert not form.is_valid()
    assert "ya está deducida" in str(form.errors["document"])


@pytest.mark.django_db
def test_dos_deducciones_sin_factura_si_conviven(scoped):
    """La restricción es por documento: sin él no hay nada que duplicar."""
    perfil = _perfil(scoped)
    _deducir(scoped, perfil, 1000)
    _deducir(scoped, perfil, 2000)

    assert summarize(scoped, perfil, ANO).personal == 3000


# --- Retenciones ------------------------------------------------------------


@pytest.mark.django_db
def test_lo_retenido_se_lleva_aparte_para_no_pagarlo_dos_veces(scoped):
    perfil = _perfil(scoped, regime=TaxProfile.Regime.LEASE)
    Withholding.objects.create(household=scoped, profile=perfil,
                               kind=Withholding.Kind.ISR,
                               amount=Decimal("14500"), date=dt.date(ANO, 5, 1))
    Withholding.objects.create(household=scoped, profile=perfil,
                               kind=Withholding.Kind.IVA,
                               amount=Decimal("3200"), date=dt.date(ANO, 5, 1))

    resumen = summarize(scoped, perfil, ANO)
    assert resumen.withheld_isr == 14500
    assert resumen.withheld_iva == 3200


@pytest.mark.django_db
def test_lo_retenido_no_baja_la_base(scoped):
    """Una retención es un pago a cuenta, no una deducción."""
    perfil = _perfil(scoped)
    _ingreso(scoped, 100000)
    Withholding.objects.create(household=scoped, profile=perfil,
                               amount=Decimal("9000"), date=dt.date(ANO, 5, 1))

    assert summarize(scoped, perfil, ANO).base == 100000


# --- El calendario ----------------------------------------------------------


@pytest.mark.django_db
def test_quien_declara_cada_mes_tiene_provisionales(scoped):
    _perfil(scoped, regime=TaxProfile.Regime.LEASE)
    obligations.materialize(scoped, HOY)

    from lares.core.models import Obligation

    mensuales = Obligation.objects.filter(source="taxes.monthly")
    assert mensuales.exists()
    assert all(o.due_on.day == 17 for o in mensuales)


@pytest.mark.django_db
def test_un_asalariado_no_tiene_pagos_provisionales(scoped):
    _perfil(scoped, regime=TaxProfile.Regime.SALARIES)
    obligations.materialize(scoped, HOY)

    from lares.core.models import Obligation

    assert not Obligation.objects.filter(source="taxes.monthly").exists()


@pytest.mark.django_db
def test_la_anual_vence_el_30_de_abril(scoped):
    _perfil(scoped, regime=TaxProfile.Regime.BUSINESS)
    obligations.materialize(scoped, HOY)

    from lares.core.models import Obligation

    anual = Obligation.objects.get(source="taxes.annual")
    assert (anual.due_on.month, anual.due_on.day) == (4, 30)
    assert -90 in anual.remind_offsets


@pytest.mark.django_db
def test_al_asalariado_se_le_dice_que_quiza_no_le_toca(scoped):
    """Generar un aviso que quizá no aplica es peor que explicar la salvedad."""
    _perfil(scoped, regime=TaxProfile.Regime.SALARIES)
    obligations.materialize(scoped, HOY)

    from lares.core.models import Obligation

    assert "dos patrones" in Obligation.objects.get(source="taxes.annual").title


@pytest.mark.django_db
def test_lo_ya_presentado_deja_de_avisar(scoped):
    perfil = _perfil(scoped, regime=TaxProfile.Regime.LEASE)
    mes = HOY.month - 1 or 12
    ano = ANO if HOY.month > 1 else ANO - 1
    Filing.objects.create(household=scoped, profile=perfil,
                          kind=Filing.Kind.MONTHLY, period=f"{ano}-{mes:02d}",
                          filed_on=HOY)
    obligations.materialize(scoped, HOY)

    from lares.core.models import Obligation

    assert not Obligation.objects.filter(
        dedupe_key=f"tax:{perfil.pk}:monthly:{ano}-{mes:02d}").exists()


# --- Lo que el sistema detecta solo -----------------------------------------


@pytest.mark.django_db
def test_avisa_de_los_meses_que_nadie_declaro(scoped):
    _perfil(scoped, regime=TaxProfile.Regime.RESICO)

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "taxes.unfiled")
    assert "sin declarar" in hallazgo.title
    assert hallazgo.severity == "high"


@pytest.mark.django_db
def test_avisa_de_una_declaracion_sin_acuse(scoped):
    """Es lo único que prueba que presentaste."""
    perfil = _perfil(scoped)
    Filing.objects.create(household=scoped, profile=perfil,
                          kind=Filing.Kind.ANNUAL, period=str(ANO - 1),
                          filed_on=dt.date(ANO, 4, 20))

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "taxes.no_receipt")
    assert "sin acuse" in hallazgo.title


@pytest.mark.django_db
def test_avisa_de_las_facturas_que_nadie_miro(scoped):
    _perfil(scoped)
    Document.objects.create(household=scoped, title="Factura", doc_type="invoice",
                            amount=Decimal("5000"), issued_on=dt.date(ANO, 3, 1))

    hallazgo = next(f for f in checks.run_all(scoped)
                    if f.check == "taxes.unmarked")
    assert "sin revisar para deducir" in hallazgo.title


@pytest.mark.django_db
def test_una_factura_ya_marcada_no_vuelve_a_aparecer(scoped):
    perfil = _perfil(scoped)
    factura = Document.objects.create(household=scoped, title="Factura",
                                      doc_type="invoice",
                                      amount=Decimal("5000"),
                                      issued_on=dt.date(ANO, 3, 1))
    _deducir(scoped, perfil, 5000, document=factura)

    assert not [f for f in checks.run_all(scoped) if f.check == "taxes.unmarked"]


@pytest.mark.django_db
def test_sin_perfil_fiscal_el_modulo_se_calla(scoped):
    """Quien no declara no debería ver ni un aviso de impuestos."""
    Document.objects.create(household=scoped, title="Factura", doc_type="invoice",
                            amount=Decimal("5000"), issued_on=dt.date(ANO, 3, 1))

    assert not [f for f in checks.run_all(scoped) if f.check.startswith("taxes.")]


# --- El paquete para el contador --------------------------------------------


@pytest.mark.django_db
def test_el_paquete_lleva_el_resumen_y_los_detalles(scoped):
    perfil = _perfil(scoped, regime=TaxProfile.Regime.LEASE)
    _ingreso(scoped, 200000)
    _deducir(scoped, perfil, 12000, description="Dentista")
    Withholding.objects.create(household=scoped, profile=perfil,
                               amount=Decimal("9000"), date=dt.date(ANO, 5, 1))

    nombre, contenido = build(scoped, perfil, ANO)
    zf = zipfile.ZipFile(io.BytesIO(contenido))

    assert nombre.endswith(".zip")
    assert set(zf.namelist()) == {"resumen.csv", "deducciones.csv",
                                  "retenciones.csv"}
    resumen = zf.read("resumen.csv").decode("utf-8-sig")
    assert "200000.00" in resumen
    assert "Dentista" in zf.read("deducciones.csv").decode("utf-8-sig")


@pytest.mark.django_db
def test_el_paquete_dice_que_no_es_una_declaracion(scoped):
    """Va dentro del archivo, no solo en la pantalla: el contador lee el CSV."""
    perfil = _perfil(scoped)
    _, contenido = build(scoped, perfil, ANO)

    resumen = zipfile.ZipFile(io.BytesIO(contenido)) \
        .read("resumen.csv").decode("utf-8-sig")
    assert "no una declaración" in resumen
    assert "corresponde al SAT o a tu contador" in resumen


@pytest.mark.django_db
def test_el_csv_abre_bien_en_excel(scoped):
    """Sin BOM, Excel en Windows parte los acentos de «Deducción»."""
    perfil = _perfil(scoped)
    _, contenido = build(scoped, perfil, ANO)

    crudo = zipfile.ZipFile(io.BytesIO(contenido)).read("resumen.csv")
    assert crudo.startswith(b"\xef\xbb\xbf")


@pytest.mark.django_db
def test_un_archivo_que_ya_no_esta_no_impide_el_paquete(scoped):
    """El CSV sigue diciendo que existió y cuál era."""
    perfil = _perfil(scoped)
    factura = Document.objects.create(household=scoped, title="Perdida",
                                      doc_type="invoice", amount=Decimal("100"),
                                      issued_on=HOY, file="documents/no-existe.pdf")
    _deducir(scoped, perfil, 100, document=factura)

    _, contenido = build(scoped, perfil, ANO)
    assert "Perdida" in zipfile.ZipFile(io.BytesIO(contenido)) \
        .read("deducciones.csv").decode("utf-8-sig")


# --- Pantallas --------------------------------------------------------------


@pytest.mark.django_db
def test_las_pantallas_de_impuestos_abren(sesion_admin, household):
    perfil = _perfil(household)

    for url in ("/impuestos/", "/impuestos/perfil/nuevo/",
                f"/impuestos/perfil/{perfil.pk}/",
                f"/impuestos/perfil/{perfil.pk}/editar/",
                "/impuestos/deducible/", "/impuestos/retencion/",
                "/impuestos/declaracion/"):
        assert sesion_admin.get(url).status_code == 200, url


@pytest.mark.django_db
def test_la_pantalla_deja_claro_que_no_declara(sesion_admin, household):
    _perfil(household)
    contenido = sesion_admin.get("/impuestos/").content.decode()

    assert "No presenta declaraciones" in contenido


@pytest.mark.django_db
def test_el_paquete_se_descarga_como_zip(sesion_admin, household):
    perfil = _perfil(household)
    respuesta = sesion_admin.get(f"/impuestos/perfil/{perfil.pk}/paquete/")

    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "application/zip"
    assert "attachment" in respuesta["Content-Disposition"]
