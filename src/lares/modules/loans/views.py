import datetime as dt

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from lares.core.services import obligations as obligation_service

from .forms import LoanPaymentForm
from .models import Loan


def loan_list(request):
    activos = [x for x in Loan.objects.filter(status=Loan.Status.ACTIVE)
               if not x.is_settled]
    me_deben = [x for x in activos if x.is_mine_to_collect]
    debo = [x for x in activos if not x.is_mine_to_collect]

    return render(request, "loans/list.html", {
        "me_deben": me_deben,
        "debo": debo,
        "total_por_cobrar": sum(x.outstanding for x in me_deben),
        "total_por_pagar": sum(x.outstanding for x in debo),
        "cerrados": [x for x in Loan.objects.filter(status=Loan.Status.ACTIVE)
                     if x.is_settled][:10],
    })


def loan_detail(request, pk):
    loan = get_object_or_404(Loan, pk=pk)
    return render(request, "loans/detail.html", {
        "loan": loan,
        "abonos": loan.payments.all()[:24],
        "tabla": loan.amortization(limit=12),
    })


def payment_new(request, pk):
    loan = get_object_or_404(Loan, pk=pk)
    form = LoanPaymentForm(request.POST or None, loan=loan,
                           household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        obligation_service.materialize(request.household)
        messages.success(request, f"Abono registrado. Quedan {loan.outstanding:,.0f}.")
        return redirect("loans:detail", pk=loan.pk)

    form.fields["date"].initial = dt.date.today()
    return render(request, "core/form.html", {
        "form": form,
        "title": ("Registrar cobro de " if loan.is_mine_to_collect
                  else "Registrar pago de ") + loan.name,
        "submit": "Registrar", "cancel_url": "loans:detail", "cancel_arg": loan.pk,
    })


def forgive(request, pk):
    """Dar por perdido lo que no va a volver, sin borrarlo."""
    loan = get_object_or_404(Loan, pk=pk)
    loan.state = Loan.State.FORGIVEN
    loan.save(update_fields=["state", "updated_at"])
    messages.success(request, f"{loan.name} queda como perdonado.")
    return redirect("loans:detail", pk=loan.pk)
