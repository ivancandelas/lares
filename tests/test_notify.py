"""Un aviso enviado no se vuelve a enviar. Es lo que sostiene la confianza."""

import datetime as dt

import pytest
from django.core import mail

from lares.core.models import Document, Membership, Obligation, User
from lares.core.services import notify, obligations

HOY = dt.date(2026, 9, 18)


@pytest.fixture
def con_miembro(scoped):
    user = User.objects.create_user(
        username="ana", email="ana@example.com", password="x"
    )
    Membership.objects.create(
        household=scoped, user=user, role=Membership.Role.OWNER,
        accepted_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    Document.objects.create(
        household=scoped, title="Licencia", doc_type="drivers_license",
        expires_on=HOY + dt.timedelta(days=30),
    )
    obligations.materialize(scoped, HOY)
    return scoped


@pytest.mark.django_db
def test_envia_los_avisos_cuya_fecha_llego(con_miembro):
    result = notify.send_due_reminders(con_miembro, HOY)
    assert result["sent"] > 0
    assert len(mail.outbox) == result["sent"]
    assert "ana@example.com" in mail.outbox[0].to


@pytest.mark.django_db
def test_no_reenvia_en_la_segunda_corrida(con_miembro):
    notify.send_due_reminders(con_miembro, HOY)
    mail.outbox.clear()

    assert notify.send_due_reminders(con_miembro, HOY)["sent"] == 0
    assert mail.outbox == []


@pytest.mark.django_db
def test_una_obligacion_ya_cumplida_no_avisa(con_miembro):
    Obligation.objects.update(status=Obligation.Status.DONE)
    mail.outbox.clear()

    result = notify.send_due_reminders(con_miembro, HOY)
    assert result["sent"] == 0
    assert mail.outbox == []
