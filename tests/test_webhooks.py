"""Los webhooks van firmados: quien los recibe puede comprobar que son de aquí."""

import hashlib
import hmac
import json
from unittest import mock

import pytest

from lares.core.models import Webhook, WebhookDelivery
from lares.core.services import webhooks


@pytest.fixture
def hook(scoped):
    return Webhook.objects.create(
        household=scoped, url="https://ejemplo.test/hook", events=["*"], secret="s3cr3t"
    )


@pytest.mark.django_db
def test_firma_el_cuerpo_exacto(scoped, hook):
    capturado = {}

    def fake_urlopen(request, timeout=None):
        capturado["body"] = request.data
        capturado["headers"] = dict(request.headers)
        return mock.MagicMock(
            status=200, __enter__=lambda s: s, __exit__=lambda *a: None
        )

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        webhooks.deliver(scoped, "obligation.completed", {"id": "123"})

    esperada = "sha256=" + hmac.new(
        b"s3cr3t", capturado["body"], hashlib.sha256
    ).hexdigest()
    assert capturado["headers"]["X-lares-signature"] == esperada
    assert json.loads(capturado["body"])["event"] == "obligation.completed"


@pytest.mark.django_db
def test_solo_recibe_los_eventos_a_los_que_se_suscribio(scoped, hook):
    hook.events = ["obligation.completed"]
    hook.save()

    with mock.patch("urllib.request.urlopen") as fake:
        webhooks.deliver(scoped, "document.classified", {})
        assert not fake.called


@pytest.mark.django_db
def test_un_endpoint_caido_no_rompe_nada_y_queda_registrado(scoped, hook):
    with mock.patch("urllib.request.urlopen", side_effect=OSError("sin ruta al host")):
        entregas = webhooks.deliver(scoped, "obligation.completed", {})

    assert len(entregas) == 1
    assert not entregas[0].ok
    assert "sin ruta" in WebhookDelivery.objects.get().error
