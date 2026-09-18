import datetime as dt

from .models import Policy


def coverage(household):
    hoy = dt.date.today()
    return {"policies": Policy.objects.filter(
        status=Policy.Status.ACTIVE, ends_on__gte=hoy
    ).order_by("ends_on")[:6]}
