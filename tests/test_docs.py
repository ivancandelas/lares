"""Que un documento no acabe escrito encima de otro.

Ha pasado dos veces, y las dos en silencio: `03-module-system.md` amaneció con
una copia vieja de la hoja de ruta dentro, y `05-roadmap.md` con el documento de
privacidad. Las dos veces fue un script de edición reutilizando una variable, y
las dos veces se descubrió de casualidad semanas o sesiones después.

La documentación vive en su propio repositorio —`docs/`, ignorado por este—,
así que estas pruebas se saltan si no está montado.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"

pytestmark = pytest.mark.skipif(not DOCS.is_dir(),
                                reason="el repo de documentación no está aquí")


def _numerados() -> list:
    return sorted(DOCS.glob("[0-9][0-9]-*.md"))


def _titulo(archivo: Path) -> str:
    primera = archivo.read_text().splitlines()[0]
    return primera.lstrip("# ").strip()


def test_cada_documento_lleva_el_titulo_que_le_toca():
    """El número del nombre y el del encabezado tienen que ser el mismo."""
    mal = []
    for archivo in _numerados():
        numero = archivo.name[:2]
        if not re.match(rf"^{numero}\s+—", _titulo(archivo)):
            mal.append(f"{archivo.name} empieza por «{_titulo(archivo)}»")

    assert not mal, ("Documentos con el título de otro (¿se escribió encima?): "
                     + "; ".join(mal))


def test_ningun_documento_es_copia_de_otro():
    vistos = {}
    repetidos = []
    for archivo in _numerados():
        titulo = _titulo(archivo)
        if titulo in vistos:
            repetidos.append(f"{archivo.name} y {vistos[titulo]}")
        vistos[titulo] = archivo.name

    assert not repetidos, f"Dos documentos con el mismo título: {repetidos}"


def test_el_handoff_existe_y_dice_de_cuando_es():
    """Es lo primero que se lee al retomar: uno sin fecha no sirve de nada."""
    handoff = DOCS / "HANDOFF.md"
    assert handoff.is_file()
    assert re.match(r"^# Handoff — \d{1,2} de \w+ de \d{4}",
                    handoff.read_text().splitlines()[0])
