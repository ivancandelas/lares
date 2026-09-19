"""Un asalariado con deducciones y alguien que renta y declara cada mes."""

import datetime as dt
from decimal import Decimal

from lares.core.models import Party

from .models import Deduction, Filing, TaxProfile, Withholding


def seed(household) -> str:
    hoy = dt.date.today()
    ano = hoy.year

    yo = Party.objects.filter(household=household, is_self=True).first()
    if not yo:
        return "impuestos: sin persona a la que atarlos"

    perfil, creado = TaxProfile.objects.get_or_create(
        household=household, taxpayer=yo,
        defaults=dict(regime=TaxProfile.Regime.LEASE, rfc="XAXX010101000",
                      started_on=dt.date(ano - 3, 1, 1),
                      note="Renta el departamento de Chapalita."),
    )
    if not creado:
        return f"impuestos: {TaxProfile.objects.count()} perfiles"

    def parte(nombre):
        p, _ = Party.objects.get_or_create(
            household=household, name=nombre,
            defaults={"kind": Party.Kind.ORGANIZATION})
        return p

    deducciones = [
        (Deduction.Kind.MEDICAL, "Consulta y estudios", 8400, 40),
        (Deduction.Kind.MEDICAL, "Dentista", 6200, 95),
        (Deduction.Kind.TUITION, "Colegiatura de Diego", 24000, 120),
        (Deduction.Kind.MEDICAL_INSURANCE, "Gastos médicos mayores", 18900, 200),
        (Deduction.Kind.DONATION, "Donativo a la Cruz Roja", 2000, 60),
    ]
    for tipo, concepto, importe, hace in deducciones:
        Deduction.objects.create(
            household=household, profile=perfil, kind=tipo,
            description=concepto, amount=Decimal(importe),
            date=hoy - dt.timedelta(days=hace),
        )

    # Una retencion de arrendamiento: quien renta a una persona moral la sufre.
    Withholding.objects.create(
        household=household, profile=perfil, kind=Withholding.Kind.ISR,
        payer=parte("Inmobiliaria del Valle"), amount=Decimal("14500"),
        date=hoy - dt.timedelta(days=75),
        note="Retención de ISR sobre la renta del departamento.",
    )

    # Tres meses presentados y los ultimos sin presentar, a proposito: asi se
    # ve el hueco que el sistema detecta solo.
    for atras in (4, 5, 6):
        mes, mes_ano = hoy.month - atras, ano
        if mes < 1:
            mes, mes_ano = mes + 12, ano - 1
        Filing.objects.create(
            household=household, profile=perfil, kind=Filing.Kind.MONTHLY,
            period=f"{mes_ano}-{mes:02d}",
            filed_on=dt.date(mes_ano, mes, 15) + dt.timedelta(days=32),
            amount_paid=Decimal("3200"),
        )

    return f"impuestos: {TaxProfile.objects.count()} perfil, " \
           f"{Deduction.objects.count()} deducciones"
