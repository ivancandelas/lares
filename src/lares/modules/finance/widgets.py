from .models import CreditCard


def cards(household):
    return {"cards": CreditCard.objects.filter(status=CreditCard.Status.ACTIVE)}
