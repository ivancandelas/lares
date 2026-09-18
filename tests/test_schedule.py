"""El evaluador de calendarios: lo comparten los packs y las reglas del usuario."""

import datetime as dt

from lares.core.schedule import next_occurrences

HOY = dt.date(2026, 9, 18)


def test_anual_toma_la_proxima_y_la_siguiente():
    fechas = next_occurrences({"yearly": {"month": 3, "day": 31}}, HOY, count=2)
    assert fechas == [dt.date(2027, 3, 31), dt.date(2028, 3, 31)]


def test_anual_incluye_hoy_si_cae_hoy():
    assert next_occurrences({"yearly": {"month": 9, "day": 18}}, HOY, count=1) == [HOY]


def test_mensual_ajusta_el_31_a_meses_cortos():
    """Un 31 en noviembre no debe reventar ni saltarse el mes."""
    fechas = next_occurrences({"monthly": {"day": 31}}, dt.date(2026, 11, 1), count=2)
    assert fechas == [dt.date(2026, 11, 30), dt.date(2026, 12, 31)]


def test_cada_n_meses_desde_una_fecha():
    fechas = next_occurrences(
        {"every": {"months": 6}, "from": "2026-01-15"}, HOY, count=2
    )
    assert fechas == [dt.date(2027, 1, 15), dt.date(2027, 7, 15)]


def test_una_sola_vez_ya_pasada_no_devuelve_nada():
    assert next_occurrences({"on_date": "2020-01-01"}, HOY) == []


def test_al_vencer_usa_la_fecha_del_documento():
    venc = dt.date(2027, 4, 30)
    assert next_occurrences({"on_expiry": True}, HOY, expires_on=venc) == [venc]
