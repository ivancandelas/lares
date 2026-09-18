import pytest

from lares.core.models import Household, Party
from lares.core.scoping import use_household


@pytest.fixture
def household(db):
    return Household.objects.create(name="Casa de prueba", slug="casa-prueba")


@pytest.fixture
def scoped(household):
    with use_household(household):
        yield household


@pytest.fixture
def me(scoped):
    return Party.objects.create(household=scoped, name="Titular", is_self=True)


@pytest.fixture(autouse=True)
def media_aislado(settings, tmp_path):
    """Ninguna prueba escribe en el almacén real de archivos."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    return settings.MEDIA_ROOT


@pytest.fixture
def sesion_admin(client, django_user_model, household):
    """Cliente autenticado, para las pruebas que pasan por una vista."""
    user = django_user_model.objects.create_user(
        username="ivan", email="ivan@example.com", password="x"
    )
    client.force_login(user)
    return client
