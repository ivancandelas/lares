"""Exportacion e importacion completas.

Es la prueba de que los datos son del usuario, no del programa. Por eso existe
desde el principio y no como funcion de salida, y por eso el formato esta
documentado: un export que nadie sabe leer no es portabilidad.

Dos propiedades que se sostienen con pruebas:

  - completo   se exporta todo modelo que cuelgue de un hogar, incluidos los
               que aporten modulos que el nucleo no conoce
  - reversible importar lo exportado reconstruye el hogar tal cual

El orden de carga se calcula, no se escribe a mano: una lista fija se
desactualiza en cuanto alguien anade un modulo.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.db import connection, transaction

FORMAT = "lares-export/1"

# No son datos del hogar: infraestructura de Django o del propio proceso.
EXCLUDED_APPS = {"contenttypes", "sessions", "admin", "auth"}


def exportable_models() -> list:
    """Modelos del hogar, ordenados para que al cargar nunca falte un padre."""
    from ..models import Household, Membership, User

    incluidos = []
    for model in apps.get_models():
        if model._meta.proxy or model._meta.auto_created:
            continue
        if model._meta.app_label in EXCLUDED_APPS and model not in (User,):
            continue
        if model in (Household, Membership, User) or _has_household(model):
            incluidos.append(model)
    return _topological(incluidos)


def _has_household(model) -> bool:
    return any(f.name == "household" for f in model._meta.fields)


def _topological(models: list) -> list:
    """Ordena por dependencias de clave foranea. Ignora las autorreferencias."""
    conjunto = set(models)
    pendientes = list(models)
    resuelto, salida = set(), []

    while pendientes:
        avanzo = False
        for model in list(pendientes):
            deps = {
                f.related_model for f in model._meta.fields
                if f.is_relation and f.related_model in conjunto
                and f.related_model is not model
            }
            if deps <= resuelto:
                salida.append(model)
                resuelto.add(model)
                pendientes.remove(model)
                avanzo = True
        if not avanzo:
            # Ciclo entre modelos: se emiten tal cual y la carga los resuelve
            # con las comprobaciones de integridad diferidas.
            salida.extend(pendientes)
            break
    return salida


def _queryset_for(model, household):
    from ..models import Household, Membership, User

    if model is Household:
        return model.objects.filter(pk=household.pk)
    if model is User:
        return model.objects.filter(memberships__household=household).distinct()
    if model is Membership or _has_household(model):
        return model._base_manager.filter(household=household)
    return model._base_manager.none()


# ---------------------------------------------------------------------------
# Exportar
# ---------------------------------------------------------------------------


def export_household(household, destination: Path) -> Path:
    """Escribe un .zip con todo el hogar. Devuelve la ruta."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data").mkdir()
        (root / "files").mkdir()

        entradas, digest = [], hashlib.sha256()
        for model in exportable_models():
            qs = _queryset_for(model, household)
            count = qs.count()
            if not count:
                continue
            etiqueta = f"{model._meta.app_label}.{model._meta.model_name}"
            payload = serializers.serialize("json", qs.iterator(), indent=2)
            ruta = root / "data" / f"{etiqueta}.json"
            ruta.write_text(payload, encoding="utf-8")
            digest.update(payload.encode("utf-8"))
            entradas.append({"model": etiqueta, "file": f"data/{etiqueta}.json",
                             "count": count})

        archivos = _copy_files(household, root / "files")

        manifest = {
            "format": FORMAT,
            "product": settings.PRODUCT_NAME,
            "exported_at": dt.datetime.now(dt.UTC).isoformat(),
            "household": {"id": str(household.pk), "name": household.name,
                          "slug": household.slug},
            "models": entradas,
            "files": archivos,
            "checksum": digest.hexdigest(),
            "note": "Contiene datos personales y las cuentas de acceso. Trátalo como un secreto.",
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(root))

    return destination


def _copy_files(household, target: Path) -> list:
    """Los binarios, incluidos los que viven fuera.

    Un documento de Paperless se referencia en el dia a dia -no tiene sentido
    tener dos veces el mismo PDF- pero una exportacion que no lo lleve deja de
    ser «la prueba de que los datos son del usuario»: seria una lista de
    titulos que solo sirve mientras la otra aplicacion siga en pie. Asi que
    aqui, y solo aqui, se trae.
    """
    from ..models import Document
    from . import paperless

    copiados = []
    for doc in Document._base_manager.filter(household=household):
        contenido = None
        if doc.file:
            try:
                with doc.file.open("rb") as origen:
                    contenido = origen.read()
            except (FileNotFoundError, ValueError):
                contenido = None
            sufijo = Path(doc.file.name).suffix
        else:
            contenido = paperless.materialize(household, doc)
            sufijo = ".pdf"

        if contenido is None:
            continue
        nombre = f"{doc.pk}{sufijo}"
        (target / nombre).write_bytes(contenido)
        copiados.append({
            "document": str(doc.pk),
            "path": f"files/{nombre}",
            "sha256": hashlib.sha256(contenido).hexdigest(),
        })
    return copiados


# ---------------------------------------------------------------------------
# Importar
# ---------------------------------------------------------------------------


@transaction.atomic
def import_household(source: Path) -> dict:
    """Reconstruye un hogar desde un export. Devuelve un resumen."""
    source = Path(source)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(source) as zf:
            zf.extractall(root)

        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != FORMAT:
            raise ValueError(f"Formato desconocido: {manifest.get('format')!r}")

        restaurados = {}
        # Las claves foraneas entre archivos se resuelven al final de la
        # transaccion, no fila a fila: asi el orden no tiene que ser perfecto.
        with connection.constraint_checks_disabled():
            for entrada in manifest["models"]:
                payload = (root / entrada["file"]).read_text(encoding="utf-8")
                n = 0
                for obj in serializers.deserialize("json", payload):
                    obj.save()
                    n += 1
                restaurados[entrada["model"]] = n

        for tabla in {m["model"].replace(".", "_") for m in manifest["models"]}:
            connection.check_constraints(table_names=[tabla])

        _restore_files(root, manifest)

    return {"household": manifest["household"], "restored": restaurados,
            "files": len(manifest.get("files", []))}


def _restore_files(root: Path, manifest: dict):
    from ..models import Document

    media = Path(settings.MEDIA_ROOT)
    for entrada in manifest.get("files", []):
        origen = root / entrada["path"]
        if not origen.exists():
            continue
        doc = Document._base_manager.filter(pk=entrada["document"]).first()
        if not doc or not doc.file:
            continue
        destino = media / doc.file.name
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origen, destino)
