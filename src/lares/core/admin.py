"""Admin de Django: andamio para los primeros meses, no la interfaz final.

Usa `all_objects` porque el admin opera fuera del ciclo de peticion con hogar
activo. En modo SaaS este admin queda restringido a staff.
"""

from django.contrib import admin

from .models import (
    Account,
    Document,
    Entry,
    Event,
    Household,
    Link,
    Membership,
    Obligation,
    ObligationRule,
    Party,
    Posting,
    Resource,
    User,
)

for model in (Household, Membership, User, Party, Resource, Link, Document,
              ObligationRule, Obligation, Event, Account, Entry, Posting):
    admin.site.register(model)
