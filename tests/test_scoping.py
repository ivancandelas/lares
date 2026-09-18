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


@pytest.mark.django_db
def test_en_mono_hogar_manda_el_mas_antiguo(client, django_user_model):
    """`Household` ordena por nombre.

    Con `first()` a secas, crear un segundo hogar llamado «Casa ajena» movía la
    instalación entera a otro sitio sin que nada avisara.
    """
    from lares.core.models import Document

    mio = Household.objects.create(name="Mi casa", slug="mia")
    with use_household(mio):
        Document.objects.create(household=mio, title="Mío")

    ajeno = Household.objects.create(name="Casa ajena", slug="ajena")
    with use_household(ajeno):
        Document.objects.create(household=ajeno, title="Ajeno")

    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    client.force_login(user)
    contenido = client.get("/documentos/").content.decode()

    assert "Mío" in contenido
    assert "Ajeno" not in contenido
