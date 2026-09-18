import datetime as dt

from .models import Belonging


def warranties(household):
    hoy = dt.date.today()
    return {"items": Belonging.objects.filter(
        status=Belonging.Status.ACTIVE,
        warranty_until__gte=hoy,
        warranty_until__lte=hoy + dt.timedelta(days=180),
    ).order_by("warranty_until")[:6]}
