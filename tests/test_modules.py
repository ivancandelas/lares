"""Contrato del sistema de modulos: el nucleo no debe conocer a los modulos."""


from lares.core.registry import registry


def test_el_modulo_registro_su_tipo_de_recurso():
    assert "vehicle" in registry.resource_kinds


def test_el_modulo_aporto_navegacion_y_widgets():
    todos = [i for g in registry.nav_grouped() for i in g["items"]]
    assert any(i.url_name == "vehicles:list" for i in todos)
    assert any(w.key == "vehicles.upcoming" for w in registry.widgets_sorted())


def test_el_menu_esta_agrupado_y_no_es_una_lista_plana():
    """Trece entradas seguidas obligan a leerlas todas para encontrar una."""
    grupos = registry.nav_grouped()
    claves = [g["key"] for g in grupos]

    assert "main" in claves
    assert {"holdings", "money"} <= set(claves)
    sueltas = next(g for g in grupos if g["key"] == "main")
    assert len(sueltas["items"]) <= 4


def test_el_nucleo_no_importa_ningun_modulo():
    """Si el nucleo importa un modulo, deja de ser un nucleo."""
    import pathlib

    core = pathlib.Path(__file__).resolve().parents[1] / "src" / "lares" / "core"
    ofensores = [
        f for f in core.rglob("*.py")
        if "lares.modules" in f.read_text()
    ]
    assert ofensores == []
