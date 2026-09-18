from .models import Property


def portfolio(household):
    activos = Property.objects.filter(status=Property.Status.ACTIVE)
    return {
        "props": activos,
        "mios": [p for p in activos if p.is_mine],
        "ajenos": [p for p in activos if not p.is_mine],
    }
