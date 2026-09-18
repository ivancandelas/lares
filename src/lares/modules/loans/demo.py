"""Los tres casos que justifican el modulo."""

import datetime as dt

from lares.core.models import Party

from .models import Loan, LoanPayment


def seed(household) -> str:
    hoy = dt.date.today()
    owner = Party.objects.filter(household=household, is_self=True).first()

    def parte(nombre, kind=Party.Kind.PERSON):
        p, _ = Party.objects.get_or_create(household=household, name=nombre,
                                           defaults={"kind": kind})
        return p

    # 1. El formal: llega un recibo cada mes, nadie lo olvida.
    hipoteca, creada = Loan.objects.get_or_create(
        household=household, name="Crédito del departamento",
        defaults=dict(
            kind="loan", direction=Loan.Direction.BORROWED,
            counterpart=parte("BBVA", Party.Kind.ORGANIZATION),
            principal=1720000, interest_kind=Loan.Interest.AMORTIZED,
            annual_rate=10.5, started_on=dt.date(2021, 9, 1), term_months=240,
            payment_amount=17180, payment_day=5, owner=owner, currency="MXN",
        ),
    )
    if creada:
        for i in range(6):
            LoanPayment.objects.create(
                household=household, loan=hipoteca,
                date=hoy - dt.timedelta(days=30 * (i + 1)),
                amount=17180, principal_part=2130, interest_part=15050,
            )

    # 2. El que diste y se evapora: nadie te manda un recibo.
    prestado, creado = Loan.objects.get_or_create(
        household=household, name="Préstamo a mi hermano",
        defaults=dict(
            kind="loan", direction=Loan.Direction.LENT,
            counterpart=parte("Luis"), principal=60000,
            interest_kind=Loan.Interest.NONE, is_informal=True,
            started_on=hoy - dt.timedelta(days=400), payment_amount=5000,
            payment_day=15, owner=owner, currency="MXN",
            description="Quedamos en 5,000 al mes hasta cubrirlo.",
        ),
    )
    if creado:
        for i in (11, 10):
            LoanPayment.objects.create(
                household=household, loan=prestado,
                date=hoy - dt.timedelta(days=30 * i), amount=5000,
            )

    # 3. El chico y de palabra, que se olvida sin más.
    Loan.objects.get_or_create(
        household=household, name="Anticipo al plomero",
        defaults=dict(
            kind="loan", direction=Loan.Direction.LENT,
            counterpart=parte("Plomería Hernández", Party.Kind.ORGANIZATION),
            principal=8000, interest_kind=Loan.Interest.NONE, is_informal=True,
            started_on=hoy - dt.timedelta(days=150), owner=owner, currency="MXN",
        ),
    )

    activos = [x for x in Loan.objects.all() if not x.is_settled]
    por_cobrar = sum(x.outstanding for x in activos if x.is_mine_to_collect)
    return f"préstamos: {len(activos)} ({por_cobrar:,.0f} por cobrar)"
