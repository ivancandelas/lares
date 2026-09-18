"""Aislamiento por hogar (tenant).

Todo dato de negocio pertenece a un Household. El hogar activo vive en un
ContextVar que fija HouseholdMiddleware en cada peticion (y las tareas de
Celery mediante `use_household`).

Esto es la primera de dos capas de aislamiento. La segunda es Row Level
Security en PostgreSQL, que se activa en modo SaaS. Ver ADR-0007: el manager
protege contra errores del programador; RLS protege contra errores del
manager.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

_current_household: ContextVar = ContextVar("lares_current_household", default=None)


def get_current_household():
    return _current_household.get()


def set_current_household(household):
    return _current_household.set(household)


@contextmanager
def use_household(household):
    token = _current_household.set(household)
    try:
        yield household
    finally:
        _current_household.reset(token)


class HouseholdQuerySet(models.QuerySet):
    def for_current_household(self):
        household = get_current_household()
        if household is None:
            return self.none()
        return self.filter(household=household)


class HouseholdManager(models.Manager.from_queryset(HouseholdQuerySet)):
    """Manager por defecto: filtra al hogar activo.

    `Modelo.objects`     -> solo el hogar activo (lo que quieres el 99% del tiempo)
    `Modelo.all_objects` -> sin filtrar (migraciones, admin, tareas de sistema)
    """

    def get_queryset(self):
        qs = super().get_queryset()
        household = get_current_household()
        if household is None:
            return qs.none()
        return qs.filter(household=household)
