"""La API: lo que hace posible que otra cosa hable con Lares.

Lo que importa aquí no es el formato JSON, es que una llave de un hogar no
pueda ver nada del otro.
"""

import datetime as dt
import json

import pytest

from lares.core.models import ApiKey, Document, Household, Obligation
from lares.core.scoping import use_household
from lares.core.services import obligations

HOY = dt.date(2026, 9, 18)


@pytest.fixture
def con_llave(scoped):
    Document.objects.create(
        household=scoped, title="Pasaporte", doc_type="passport",
        expires_on=dt.date(2027, 5, 16),
    )
    obligations.materialize(scoped, HOY)
    _, token = ApiKey.issue(scoped, "pruebas")
    return scoped, token


@pytest.mark.django_db
def test_sin_llave_no_se_entra(client):
    response = client.get("/api/v1/agenda")
    assert response.status_code == 401
    assert "X-Lares-Key" in response.json()["error"]


@pytest.mark.django_db
def test_una_llave_inventada_no_sirve(client, con_llave):
    response = client.get("/api/v1/agenda", headers={"X-Lares-Key": "abcd1234.loquesea"})
    assert response.status_code == 401


@pytest.mark.django_db
def test_lee_la_agenda_con_llave(client, con_llave):
    _, token = con_llave
    response = client.get("/api/v1/agenda", headers={"X-Lares-Key": token})

    assert response.status_code == 200
    data = response.json()
    assert data["today"] == str(dt.date.today())
    titulos = [o["title"] for o in data["overdue"] + data["this_week"] + data["later"]]
    assert "Renovar Pasaporte" in titulos


@pytest.mark.django_db
def test_una_llave_no_ve_los_datos_de_otro_hogar(client, con_llave):
    _, token = con_llave
    ajeno = Household.objects.create(name="Casa ajena", slug="ajena")
    with use_household(ajeno):
        Document.objects.create(
            household=ajeno, title="Escritura secreta", doc_type="deed",
            expires_on=dt.date(2027, 1, 1),
        )

    response = client.get("/api/v1/documents", headers={"X-Lares-Key": token})
    titulos = [d["title"] for d in response.json()["results"]]
    assert titulos == ["Pasaporte"]


@pytest.mark.django_db
def test_una_llave_revocada_deja_de_servir(client, con_llave):
    scoped, token = con_llave
    ApiKey.all_objects.update(revoked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))

    assert client.get("/api/v1/agenda", headers={"X-Lares-Key": token}).status_code == 401


@pytest.mark.django_db
def test_los_huecos_se_consultan_por_api(client, con_llave):
    _, token = con_llave
    response = client.get("/api/v1/gaps", headers={"X-Lares-Key": token})
    assert response.status_code == 200
    assert isinstance(response.json()["results"], list)


@pytest.mark.django_db
def test_escribir_exige_llave_aunque_haya_sesion(client, con_llave, django_user_model):
    scoped, _ = con_llave
    with use_household(scoped):
        obligation = Obligation.objects.first()

    user = django_user_model.objects.create_user(
        username="a", email="a@example.com", password="x"
    )
    client.force_login(user)

    response = client.post(f"/api/v1/obligations/{obligation.pk}/complete")
    assert response.status_code == 401


@pytest.mark.django_db
def test_completar_una_obligacion_con_llave(client, con_llave):
    scoped, token = con_llave
    with use_household(scoped):
        obligation = Obligation.objects.first()

    response = client.post(
        f"/api/v1/obligations/{obligation.pk}/complete",
        headers={"X-Lares-Key": token},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "done"

    obligation.refresh_from_db()
    assert obligation.status == Obligation.Status.DONE


@pytest.mark.django_db
def test_alta_de_webhook_devuelve_el_secreto_una_vez(client, con_llave):
    _, token = con_llave
    response = client.post(
        "/api/v1/webhooks",
        data=json.dumps({"url": "https://ejemplo.test/hook", "events": ["*"]}),
        content_type="application/json",
        headers={"X-Lares-Key": token},
    )
    assert response.status_code == 201
    assert response.json()["secret"]
