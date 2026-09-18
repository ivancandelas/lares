"""Contrato del sistema de modulos: el nucleo no debe conocer a los modulos."""


from lares.core.registry import registry


def test_el_modulo_registro_su_tipo_de_recurso():
    assert "vehicle" in registry.resource_kinds


def test_el_modulo_aporto_navegacion_y_widgets():
    assert any(i.url_name == "vehicles:list" for i in registry.nav_sorted())
    assert any(w.key == "vehicles.upcoming" for w in registry.widgets_sorted())


def test_el_nucleo_no_importa_ningun_modulo():
    """Si el nucleo importa un modulo, deja de ser un nucleo."""
    import pathlib

    core = pathlib.Path(__file__).resolve().parents[1] / "src" / "lares" / "core"
    ofensores = [
        f for f in core.rglob("*.py")
        if "lares.modules" in f.read_text()
    ]
    assert ofensores == []
