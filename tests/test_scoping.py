"""El aislamiento por hogar es la garantia sobre la que se construye el SaaS.

Si estas pruebas fallan, un hogar puede ver datos de otro.
"""

import pytest

from lares.core.models import Household, Party
from lares.core.scoping import use_household


@pytest.mark.django_db
def test_sin_hogar_activo_no_se_ve_nada():
    otro = Household.objects.create(name="Otra casa", slug="otra")
    with use_household(otro):
        Party.objects.create(household=otro, name="Ajeno")

    assert Party.objects.count() == 0          # sin contexto: nada
    assert Party.all_objects.count() == 1      # el dato existe


@pytest.mark.django_db
def test_un_hogar_no_ve_los_datos_de_otro():
    a = Household.objects.create(name="A", slug="a")
    b = Household.objects.create(name="B", slug="b")
    with use_household(a):
        Party.objects.create(household=a, name="De A")
    with use_household(b):
        Party.objects.create(household=b, name="De B")

    with use_household(a):
        assert [p.name for p in Party.objects.all()] == ["De A"]
    with use_household(b):
        assert [p.name for p in Party.objects.all()] == ["De B"]
