"""Nada es publico: la instalacion puede estar expuesta."""

import pytest


@pytest.mark.django_db
def test_el_tablero_exige_sesion(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith("/entrar/")


@pytest.mark.django_db
def test_la_pantalla_de_entrada_es_publica(client):
    assert client.get("/entrar/").status_code == 200
