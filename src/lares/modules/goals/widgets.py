def goals(household):
    """Las metas que peor van, primero: son las que piden una decisión."""
    from .models import Goal

    metas = [m for m in Goal.objects.filter(is_active=True) if not m.is_reached]
    metas.sort(key=lambda m: (-(m.months_late or -99), m.progress))
    return {"metas": metas[:4], "cuantas": len(metas)}
