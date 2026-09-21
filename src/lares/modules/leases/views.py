import datetime as dt

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from lares.core.services import obligations as obligation_service

from .forms import RentPaymentForm
from .models import Lease, RentPayment
from .services import ensure_periods, limpiar_lo_anterior, performance


def lease_list(request):
    activos = [x for x in Lease.objects.filter(status=Lease.Status.ACTIVE)]
    cobro = [x for x in activos if x.is_landlord]
    pago = [x for x in activos if not x.is_landlord]

    for lease in activos:
        ensure_periods(lease)

    return render(request, "leases/list.html", {
        "cobro": cobro,
        "pago": pago,
        "ingreso_mensual": sum(x.rent_amount for x in cobro if x.is_live),
        "gasto_mensual": sum(x.rent_amount for x in pago if x.is_live),
        "atrasados": [p for x in activos for p in x.overdue_payments],
    })


def lease_detail(request, pk):
    lease = get_object_or_404(Lease, pk=pk)
    ensure_periods(lease)
    from .services import next_rent

    return render(request, "leases/detail.html", {
        "lease": lease,
        "pagos": lease.payments.all()[:24],
        "atrasados": lease.overdue_payments,
        "proxima_renta": next_rent(lease),
    })


def start_tracking_here(request, pk):
    """«De aquí para atrás, saldado»: pone la fecha de control en hoy.

    Es la salida para quien ya tiene el destrozo hecho. Dar de alta un
    contrato de hace cuatro anos creaba 48 meses sin cobrar, y la unica forma
    de limpiarlos era registrar cuarenta y ocho pagos a mano. Nadie hace eso:
    lo que hace es dejar de mirar la pantalla.

    Solo borra los meses intactos. Uno con cobro anotado es un dato de
    alguien, y para recuperar los borrados basta con bajar la fecha.
    """
    lease = get_object_or_404(Lease, pk=pk)
    lease.tracked_from = dt.date.today()
    lease.save(update_fields=["tracked_from", "updated_at"])

    borrados = limpiar_lo_anterior(lease)
    obligation_service.materialize(request.household)
    messages.success(
        request,
        f"{borrados} mes{'es' if borrados != 1 else ''} anterior"
        f"{'es' if borrados != 1 else ''} dado"
        f"{'s' if borrados != 1 else ''} por saldado"
        f"{'s' if borrados != 1 else ''} fuera de aquí."
        if borrados else "A partir de hoy se lleva el control aquí."
    )
    return redirect("leases:detail", pk=lease.pk)


def payment_register(request, pk):
    pago = get_object_or_404(RentPayment, pk=pk)
    form = RentPaymentForm(request.POST or None, instance=pago, payment=pago,
                           household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        obligation_service.materialize(request.household)
        verbo = "Cobro" if pago.lease.is_landlord else "Pago"
        messages.success(request, f"{verbo} de {pago.period} registrado.")
        return redirect("leases:detail", pk=pago.lease_id)

    return render(request, "core/form.html", {
        "form": form,
        "title": ("Registrar el cobro de " if pago.lease.is_landlord
                  else "Registrar el pago de ") + pago.period,
        "submit": "Registrar", "cancel_url": "leases:detail",
        "cancel_arg": pago.lease_id,
    })


def deposit_returned(request, pk):
    """Cerrar el depósito: devuelto o recuperado."""
    lease = get_object_or_404(Lease, pk=pk)
    lease.deposit_returned_on = dt.date.today()
    lease.deposit_returned_amount = lease.deposit_amount
    lease.save(update_fields=["deposit_returned_on", "deposit_returned_amount",
                              "updated_at"])
    messages.success(request, "Depósito cerrado.")
    return redirect("leases:detail", pk=lease.pk)


def yields(request):
    """Cuánto renta cada inmueble después de lo que cuesta tenerlo."""
    return render(request, "leases/yields.html",
                  {"rendimientos": performance(request.household)})
