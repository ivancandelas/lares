"""Lo que se pierde de vista entre una declaración y la siguiente."""

import datetime as dt

from lares.core.registry import Check, Finding

from .models import Deduction, Filing, TaxProfile
from .services import summarize


class DeductibleUnmarked(Check):
    """Facturas a tu nombre que nadie marcó como deducibles.

    El CFDI ya esta dentro, con su RFC y su importe. Lo unico que falta es un
    clic, y de no darlo depende buena parte de lo que se deja de deducir cada
    ano.
    """

    key = "taxes.unmarked"
    label = "Facturas sin revisar"
    severity = "low"

    def run(self, household):
        from lares.core.models import Document

        perfiles = list(TaxProfile.objects.filter(is_active=True))
        if not perfiles:
            return []

        ano = dt.date.today().year
        marcados = set(
            Deduction.objects.filter(document__isnull=False)
            .values_list("document_id", flat=True)
        )
        sueltas = [
            d for d in Document.objects.filter(doc_type="invoice",
                                               issued_on__year=ano)
            if d.pk not in marcados
        ]
        if not sueltas:
            return []
        total = sum(d.amount or 0 for d in sueltas)
        return [Finding(
            check=self.key,
            title=f"{len(sueltas)} facturas de {ano} sin revisar para deducir",
            detail=(f"Suman {total:,.0f}. No todas serán deducibles, pero "
                    f"ninguna lo será si nadie las mira."),
            severity=self.severity,
        )]


class OverCap(Check):
    """Deducciones personales por encima del tope.

    Deducir de mas no es gratis: la diferencia no cuenta, y si la declaracion
    se presento contando con ella, el saldo a favor esperado no llega.
    """

    key = "taxes.over_cap"
    label = "Deducciones por encima del tope"
    severity = "normal"

    def run(self, household):
        ano = dt.date.today().year
        hallazgos = []
        for perfil in TaxProfile.objects.filter(is_active=True):
            resumen = summarize(household, perfil, ano)
            if resumen.over_cap <= 0:
                continue
            tope = min((c.limit for c in resumen.caps if c.limit), default=None)
            hallazgos.append(Finding(
                check=self.key,
                title=f"{perfil.taxpayer}: {resumen.over_cap:,.0f} de "
                      f"deducciones que no van a contar",
                detail=(f"Llevas {resumen.personal:,.0f} en deducciones "
                        f"personales y el tope es {tope:,.0f}."),
                severity=self.severity,
                subject_type="tax_profile", subject_id=perfil.pk,
            ))
        return hallazgos


class MissingUma(Check):
    """Sin la UMA del ejercicio, el tope se queda a medias."""

    key = "taxes.no_uma"
    label = "Falta la UMA del ejercicio"
    severity = "low"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{perfil.taxpayer}: falta el valor de la UMA",
                detail="El tope de las deducciones personales es el menor "
                       "entre el 15% de tus ingresos y cinco UMA anuales. Sin "
                       "la UMA solo se aplica el primero, y el total real "
                       "puede ser menor.",
                severity=self.severity,
                subject_type="tax_profile", subject_id=perfil.pk,
            )
            for perfil in TaxProfile.objects.filter(is_active=True,
                                                    uma_annual__isnull=True)
            if perfil.deductions.exists()
        ]


class FilingWithoutReceipt(Check):
    """Una declaración presentada sin el acuse guardado.

    El acuse es lo unico que prueba que presentaste. El dia que alguien lo
    pide, no tenerlo equivale a no haber presentado.
    """

    key = "taxes.no_receipt"
    label = "Declaración sin acuse"
    severity = "normal"

    def run(self, household):
        return [
            Finding(
                check=self.key,
                title=f"{declaracion} sin acuse guardado",
                detail="Es lo único que prueba que presentaste.",
                severity=self.severity,
                subject_type="filing", subject_id=declaracion.pk,
            )
            for declaracion in Filing.objects.filter(filed_on__isnull=False,
                                                     receipt__isnull=True)
        ]


class UnfiledPeriod(Check):
    """Meses cerrados que nadie declaró ni marcó como declarados."""

    key = "taxes.unfiled"
    label = "Periodo sin declarar"
    severity = "high"

    def run(self, household):
        hoy = dt.date.today()
        hallazgos = []
        for perfil in TaxProfile.objects.filter(is_active=True):
            if not perfil.files_monthly:
                continue
            presentados = set(
                Filing.objects.filter(profile=perfil, kind=Filing.Kind.MONTHLY,
                                      filed_on__isnull=False)
                .values_list("period", flat=True)
            )
            faltan = []
            for atras in range(1, 7):
                mes, ano = hoy.month - atras, hoy.year
                if mes < 1:
                    mes, ano = mes + 12, ano - 1
                periodo = f"{ano}-{mes:02d}"
                vence_mes = mes % 12 + 1
                vence = dt.date(ano + (1 if mes == 12 else 0), vence_mes, 17)
                if vence < hoy and periodo not in presentados:
                    faltan.append(periodo)
            if not faltan:
                continue
            hallazgos.append(Finding(
                check=self.key,
                title=f"{perfil.taxpayer}: {len(faltan)} "
                      f"{'mes' if len(faltan) == 1 else 'meses'} sin declarar",
                detail=(f"El más viejo es {min(faltan)}. Los recargos corren "
                        f"desde la fecha límite, no desde que te enteras."),
                severity=self.severity,
                subject_type="tax_profile", subject_id=perfil.pk,
            ))
        return hallazgos
