from .models import Loan


def balance(household):
    activos = [x for x in Loan.objects.filter(status=Loan.Status.ACTIVE)
               if not x.is_settled]
    return {
        "por_cobrar": sum(x.outstanding for x in activos if x.is_mine_to_collect),
        "por_pagar": sum(x.outstanding for x in activos if not x.is_mine_to_collect),
        "loans": sorted(activos, key=lambda x: -x.outstanding)[:5],
    }
