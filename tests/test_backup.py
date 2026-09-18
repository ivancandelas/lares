"""Copias cifradas. Una copia que no se ha restaurado nunca no es una copia."""

import pytest

from lares.core.models import Household, Party
from lares.core.services import backup
from lares.modules.vehicles.models import Vehicle

FRASE = "frase-de-prueba-que-no-es-un-secreto-real"


@pytest.fixture
def hogar(scoped, me):
    Vehicle.objects.create(
        household=scoped, name="Mazda CX-5", kind="vehicle", plates="JGT1234", owner=me
    )
    return scoped


@pytest.mark.django_db
def test_la_copia_no_deja_datos_legibles_en_el_archivo(hogar, tmp_path):
    ruta = backup.backup_household(hogar, tmp_path / "copia.lares", FRASE)
    crudo = ruta.read_bytes()

    assert crudo.startswith(backup.MAGIC)
    # Nada del contenido debe poder leerse abriendo el archivo con un editor.
    for secreto in (b"Mazda", b"JGT1234", hogar.slug.encode()):
        assert secreto not in crudo


@pytest.mark.django_db
def test_restaurar_reconstruye_el_hogar(hogar, tmp_path):
    ruta = backup.backup_household(hogar, tmp_path / "copia.lares", FRASE)
    slug = hogar.slug
    Household.objects.filter(pk=hogar.pk).delete()

    result = backup.restore_household(ruta, FRASE)

    assert result["household"]["slug"] == slug
    restaurado = Household.objects.get(slug=slug)
    from lares.core.scoping import use_household
    with use_household(restaurado):
        assert Vehicle.objects.get().plates == "JGT1234"
        assert Party.objects.filter(is_self=True).exists()


@pytest.mark.django_db
def test_una_frase_equivocada_falla_con_un_mensaje_claro(hogar, tmp_path):
    ruta = backup.backup_household(hogar, tmp_path / "copia.lares", FRASE)

    with pytest.raises(backup.BadPassphrase, match="no abre esta copia"):
        backup.restore_household(ruta, "otra frase")


@pytest.mark.django_db
def test_un_archivo_alterado_no_se_restaura(hogar, tmp_path):
    ruta = backup.backup_household(hogar, tmp_path / "copia.lares", FRASE)
    crudo = bytearray(ruta.read_bytes())
    crudo[-20] ^= 0xFF                      # un solo bit cambiado
    ruta.write_bytes(bytes(crudo))

    with pytest.raises(backup.BadPassphrase):
        backup.restore_household(ruta, FRASE)


@pytest.mark.django_db
def test_dos_copias_de_lo_mismo_no_son_identicas(hogar, tmp_path):
    """Cada copia lleva su propia sal: dos archivos iguales delatarían el contenido."""
    a = backup.backup_household(hogar, tmp_path / "a.lares", FRASE).read_bytes()
    b = backup.backup_household(hogar, tmp_path / "b.lares", FRASE).read_bytes()
    assert a != b


@pytest.mark.django_db
def test_rechaza_un_archivo_que_no_es_una_copia(tmp_path):
    ruta = tmp_path / "cualquiera.txt"
    ruta.write_bytes(b"esto no es una copia")

    with pytest.raises(ValueError, match="no es una copia de Lares"):
        backup.restore_household(ruta, FRASE)
