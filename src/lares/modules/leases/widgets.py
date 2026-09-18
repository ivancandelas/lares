from .models import Lease


def rent(household):
    activos = [x for x in Lease.objects.filter(status=Lease.Status.ACTIVE)
               if x.is_live]
    return {
        "cobro": sum(x.rent_amount for x in activos if x.is_landlord),
        "pago": sum(x.rent_amount for x in activos if not x.is_landlord),
        "atrasos": sum(len(x.overdue_payments) for x in activos),
        "leases": activos[:5],
    }
