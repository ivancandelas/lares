"""Los topes mensuales pasan a ser líneas del presupuesto del año.

Eran dos numeros para la misma categoria -un tope al mes y un previsto anual- y
en cuanto uno se ajusta y el otro no, los dos dejan de ser fiables. Ahora es una
sola cifra que dice si es al mes o en todo el periodo.
"""

import datetime as dt

from django.db import migrations


def adelante(apps, schema_editor):
    Budget = apps.get_model("finance", "Budget")
    Plan = apps.get_model("finance", "Plan")
    PlanLine = apps.get_model("finance", "PlanLine")

    ano = dt.date.today().year
    for tope in Budget.objects.all():
        plan, _ = Plan.objects.get_or_create(
            household_id=tope.household_id, kind="annual", year=ano,
            defaults={"name": f"Presupuesto {ano}", "currency": "MXN",
                      "is_active": True,
                      "note": "Creado al unificar los topes de gasto."},
        )
        if PlanLine.objects.filter(plan=plan, account_id=tope.account_id).exists():
            continue
        PlanLine.objects.create(
            household_id=tope.household_id, plan=plan,
            account_id=tope.account_id, amount=tope.amount,
            cadence="monthly", note=tope.note or "",
        )


def atras(apps, schema_editor):
    Budget = apps.get_model("finance", "Budget")
    PlanLine = apps.get_model("finance", "PlanLine")

    for linea in PlanLine.objects.filter(cadence="monthly"):
        Budget.objects.get_or_create(
            household_id=linea.household_id, account_id=linea.account_id,
            defaults={"amount": linea.amount, "is_active": True,
                      "note": linea.note},
        )


class Migration(migrations.Migration):
    dependencies = [("finance", "0008_cadencia_de_linea")]
    operations = [migrations.RunPython(adelante, atras)]
