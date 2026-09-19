import datetime as dt


def taxes(household):
    """Lo próximo que vence y cuánto llevas deducido este año."""
    from .models import Filing, TaxProfile
    from .services import summarize

    ano = dt.date.today().year
    perfiles = list(TaxProfile.objects.filter(is_active=True)
                    .select_related("taxpayer"))
    resumenes = [summarize(household, p, ano) for p in perfiles]
    return {
        "resumenes": resumenes,
        "ano": ano,
        "sin_declarar": Filing.objects.filter(filed_on__isnull=True).count(),
    }
