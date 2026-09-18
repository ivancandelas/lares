from .models import Subscription


def cost(household):
    activas = list(Subscription.objects.filter(status=Subscription.Status.ACTIVE))
    return {
        "subs": sorted(activas, key=lambda s: -(s.yearly_cost or 0))[:5],
        "anual": sum(s.yearly_cost or 0 for s in activas),
        "total": len(activas),
    }
