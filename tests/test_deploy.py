"""Los scripts de despliegue, vigilados desde la batería.

No prueban un despliegue -eso necesita una máquina- pero sí lo que se rompe
sin que nadie lo note: un script con un error de sintaxis, una unit que apunta
a una ruta que ya no existe, o el one-liner de Proxmox señalando a una carpeta
que alguien movió. Los tres fallan en el peor momento: cuando alguien instala.
"""

import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPTS = sorted([*RAIZ.glob("deploy/**/*.sh"), *RAIZ.glob("docker/*.sh")])
UNITS = sorted(RAIZ.glob("deploy/native/systemd/*.service"))


def test_hay_scripts_que_vigilar():
    """Si esto falla es que se movieron de sitio y las demás pruebas mienten."""
    assert len(SCRIPTS) >= 4
    assert len(UNITS) == 3


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_cada_script_es_sintacticamente_valido(script):
    interprete = "bash" if "bash" in script.read_text().splitlines()[0] else "sh"
    resultado = subprocess.run([interprete, "-n", str(script)],
                               capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.name)
def test_cada_unit_arranca_desde_el_enlace_current(unit):
    """`current` es lo que hace que volver atrás sea mover un enlace.

    Una unit que apuntara a una versión concreta dejaría el rollback a medias:
    el enlace volvería y el servicio seguiría ejecutando la otra.
    """
    texto = unit.read_text()
    ejecutable = re.search(r"^ExecStart=(\S+)", texto, re.M).group(1)

    assert ejecutable.startswith("/opt/lares/current/")
    assert "EnvironmentFile=/opt/lares/lares.env" in texto
    assert "User=lares" in texto


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.name)
def test_ninguna_unit_escribe_donde_no_debe(unit):
    """Endurecerlas es barato; descubrir que no lo estaban, no."""
    texto = unit.read_text()

    assert "NoNewPrivileges=true" in texto
    assert "ProtectSystem=strict" in texto
    # Y con eso puesto, hay que decir explícitamente dónde SÍ se escribe, o la
    # aplicación no puede guardar ni un documento.
    assert "/opt/lares/data" in re.search(r"^ReadWritePaths=(.*)$", texto,
                                          re.M).group(1)


def test_el_one_liner_de_proxmox_apunta_a_donde_viven_los_scripts():
    """Mover `deploy/proxmox/` sin tocar la URL deja el one-liner roto."""
    ct = (RAIZ / "deploy/proxmox/ct/lares.sh").read_text()
    url = re.search(r'COMMUNITY_SCRIPTS_URL="\$\{COMMUNITY_SCRIPTS_URL:-(.*?)\}"',
                    ct).group(1)

    assert url.endswith("/deploy/proxmox")
    assert (RAIZ / "deploy/proxmox/ct").is_dir()
    assert (RAIZ / "deploy/proxmox/install/lares-install.sh").is_file()


def test_el_instalador_nativo_y_el_actualizador_hablan_de_la_misma_casa():
    """Dos rutas distintas y la actualización no encuentra lo que se instaló."""
    instalar = (RAIZ / "deploy/native/install.sh").read_text()
    actualizar = (RAIZ / "deploy/native/update.sh").read_text()

    assert 'RAIZ="/opt/lares"' in instalar
    assert 'RAIZ="/opt/lares"' in actualizar
    # Y los dos migran con el mismo comando, que es donde vive el candado.
    assert "migrate_locked" in instalar
    assert "migrate_locked" in actualizar


def test_la_imagen_migra_con_el_mismo_comando():
    entrypoint = (RAIZ / "docker/entrypoint.sh").read_text()

    assert "migrate_locked" in entrypoint


@pytest.mark.parametrize("script", ["install.sh", "update.sh"])
def test_hay_respaldo_cuando_no_existe_el_release(script):
    """Empujar una etiqueta no crea un Release, y el instalador preguntaba solo
    por el Release.

    La primera instalación de la primera versión moría con un `404` crudo
    después de veinte minutos compilando dependencias. Que consulte también las
    etiquetas es lo que separa «funciona recién publicado» de «funciona si
    además te acordaste de publicar el Release a mano».
    """
    texto = (RAIZ / "deploy/native" / script).read_text()

    assert "/releases/latest" in texto
    assert "/tags" in texto
    # Y si de verdad no hay ninguna, se dice qué hacer en vez de morir con el
    # código de salida de curl.
    assert "sin_versiones" in texto


@pytest.mark.django_db
def test_salud_no_dice_la_version_a_cualquiera(client):
    """La versión exacta es lo primero que busca quien va a atacar esto.

    Hacia dentro sí se dice: el actualizador la necesita para distinguir
    «levantó» de «levantó lo nuevo». Desde fuera, `ok` y nada más.
    """
    from django.conf import settings

    de_dentro = client.get("/salud", REMOTE_ADDR="127.0.0.1").json()
    assert de_dentro["version"] == settings.VERSION

    # Detrás del proxy la dirección de origen puede seguir siendo loopback -si
    # el proxy vive en la misma máquina-, así que lo que decide es la cabecera
    # que el proxy añade al reenviar.
    de_fuera = client.get("/salud", REMOTE_ADDR="127.0.0.1",
                          HTTP_X_FORWARDED_FOR="203.0.113.7").json()
    assert de_fuera == {"ok": True}

    remoto = client.get("/salud", REMOTE_ADDR="192.168.1.50").json()
    assert remoto == {"ok": True}


@pytest.mark.parametrize("script", ["install.sh", "update.sh"])
def test_las_ordenes_quedan_en_un_path_minimo(script):
    """`pct enter` -cómo se entra a un LXC desde el nodo Proxmox- abre la shell
    con un PATH mínimo que no incluye `/usr/local/bin`.

    Con el enlace solo ahí, `lares-update` contesta «command not found» aunque
    esté perfectamente instalado, y la persona se queda parada en la orden que
    le dijimos que tecleara. `/usr/bin` sí está en ese PATH.
    """
    texto = (RAIZ / "deploy/native" / script).read_text()

    assert "/usr/local/bin" in texto
    assert "/usr/bin" in texto
    for orden in ("lares-update", "lares-manage"):
        assert f'"$bin_dir/{orden}"' in texto
