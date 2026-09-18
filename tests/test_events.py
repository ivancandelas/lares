"""La linea de tiempo es append-only: es auditoria, no un log cualquiera."""

import pytest

from lares.core.models import Event


@pytest.mark.django_db
def test_evento_no_se_puede_modificar(household):
    event = Event.objects.create(household=household, verb="test.created")
    event.verb = "test.modified"
    with pytest.raises(RuntimeError):
        event.save()


@pytest.mark.django_db
def test_evento_no_se_puede_borrar(household):
    event = Event.objects.create(household=household, verb="test.created")
    with pytest.raises(RuntimeError):
        event.delete()
