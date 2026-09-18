import datetime as dt

from lares.core.models import Obligation

from .models import Vehicle


def upcoming(household):
    horizon = dt.date.today() + dt.timedelta(days=90)
    return {
        "vehicles": Vehicle.objects.filter(status=Vehicle.Status.ACTIVE),
        "obligations": Obligation.objects.filter(
            source__startswith="vehicles.",
            status=Obligation.Status.PENDING,
            due_on__lte=horizon,
        )[:10],
    }
