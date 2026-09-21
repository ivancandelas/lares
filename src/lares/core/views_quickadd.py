"""El alta rapida que se abre encima del formulario que estabas llenando.

Dos respuestas y ninguna pantalla: `GET` devuelve el trozo de formulario que
va dentro de la ventana, y `POST` crea y contesta en JSON lo justo para que el
desplegable de atras se actualice solo. Ver `quickadd.py` para el porque.
"""

from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from . import quickadd
from .permissions import scope_of


def _permitido(request, alta) -> bool:
    """Crear una cuenta desde un desplegable sigue siendo crear una cuenta.

    Sin esto, el alta rapida seria un agujero por el que quien tiene el dinero
    restringido crea cuentas: la puerta de la pantalla estaria cerrada y la de
    al lado abierta.
    """
    membresia = getattr(request, "membership", None)
    if membresia is None:          # self-hosted: un hogar, sin ambitos
        return True
    if not (membresia.is_live and membresia.can_write):
        return False
    return membresia.sees(alta.scope) and (
        alta.scope != "admin" or membresia.can_admin
    )


@require_http_methods(["GET", "POST"])
def quick_add(request, key):
    alta = quickadd.get(key)
    if alta is None:
        raise Http404
    if not _permitido(request, alta):
        return JsonResponse({"error": "No puedes crear esto."}, status=403)

    # El desplegable desde el que se abrio dice de que tipo tiene que ser lo
    # que se cree: la categoria de un gasto es una cuenta, pero no cualquiera.
    preset = request.GET.get("preset") or ""
    inicial = {alta.preset_field: preset} if (preset and alta.preset_field) else {}

    form = alta.form(request.POST or None, household=request.household,
                     initial=inicial)
    if preset and alta.preset_field in form.fields:
        # Fijo, no sugerido: si se pudiera cambiar, desde "categoria de gasto"
        # se crearia una cuenta de activo que luego no aparece en el
        # desplegable, y el usuario ve que su alta "no hizo nada".
        form.fields[alta.preset_field].disabled = True
        form.fields[alta.preset_field].initial = preset

    if request.method == "POST" and form.is_valid():
        objeto = form.save()
        return JsonResponse({"id": str(objeto.pk), "label": str(objeto)})

    titulo = (alta.preset_labels or {}).get(preset) or alta.title
    contexto = {"form": form, "title": titulo, "key": key, "preset": preset}
    estado = 422 if request.method == "POST" else 200
    return render(request, "core/_quickadd.html", contexto, status=estado)


def scope_de(key: str) -> str:
    """Para las pruebas: a que ambito pertenece crear esto."""
    alta = quickadd.get(key)
    return alta.scope if alta else scope_of("", "core")
