"""Varios usuarios en un hogar, con permisos que de verdad restringen.

Dos ejes que se combinan y que no son lo mismo:

    rol      lo que puede HACER  (mirar, registrar, administrar)
    ámbitos  sobre QUÉ           (dinero, casa, coches, impuestos)

Lo que más se prueba aquí es que **bloquea**, no que esconde. Quitar una
entrada del menú no es un permiso: la dirección se puede teclear, y quien la
teclea suele ser justo quien no debería entrar.
"""

import datetime as dt

import pytest
from django.urls import reverse

from lares.core.models import Household, Membership, User

HOY = dt.date.today()


@pytest.fixture
def multi(settings):
    settings.TENANCY_MODE = "multi"
    return settings


@pytest.fixture
def casa(db):
    return Household.objects.create(name="Casa", slug="casa")


def _miembro(casa, correo, rol=Membership.Role.MEMBER, scopes=None,
             acepta=True, caduca=None):
    user = User.objects.create_user(username=correo, email=correo,
                                    password="x", display_name=correo)
    from django.utils import timezone

    return Membership.objects.create(
        household=casa, user=user, role=rol, scopes=scopes or [],
        expires_on=caduca,
        accepted_at=timezone.now() if acepta else None,
    )


def _sesion(client, membresia):
    client.force_login(membresia.user)
    return client


# --- El rol dice lo que puede hacer -----------------------------------------


@pytest.mark.django_db
def test_el_titular_lo_puede_todo(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    assert yo.can_admin and yo.can_write and yo.sees_everything
    assert _sesion(client, yo).get("/hogar/").status_code == 200


@pytest.mark.django_db
def test_solo_lectura_puede_mirar_pero_no_registrar(multi, casa, client):
    """Mirar no es escribir. El 403 va en el POST, no en la pantalla."""
    invitado = _miembro(casa, "invitado@x.mx", Membership.Role.VIEWER)
    sesion = _sesion(client, invitado)

    assert sesion.get("/").status_code == 200
    assert sesion.post("/gastos/nuevo/", {}).status_code == 403


@pytest.mark.django_db
def test_un_miembro_normal_si_registra(multi, casa, client):
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER)

    # 200 es el formulario con errores, que es lo correcto: le dejó entrar.
    assert _sesion(client, hijo).post("/gastos/nuevo/", {}).status_code == 200


@pytest.mark.django_db
def test_administrar_el_hogar_es_solo_de_quien_administra(multi, casa, client):
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.ADULT)

    assert _sesion(client, hijo).get("/hogar/").status_code == 403


# --- Los ámbitos dicen sobre qué --------------------------------------------


@pytest.mark.django_db
def test_sin_el_ambito_de_dinero_no_se_entra_aunque_se_teclee(multi, casa,
                                                               client):
    """Es la prueba que importa: esconder el menú no habría bastado."""
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER,
                    scopes=["tasks"])
    sesion = _sesion(client, hijo)

    assert sesion.get("/dinero/").status_code == 403
    assert sesion.get("/se-debe/").status_code == 403
    assert sesion.get("/recurrentes/").status_code == 403


@pytest.mark.django_db
def test_con_el_ambito_concedido_si_se_entra(multi, casa, client):
    pareja = _miembro(casa, "pareja@x.mx", Membership.Role.ADULT,
                      scopes=["finance", "tasks"])

    assert _sesion(client, pareja).get("/dinero/").status_code == 200


@pytest.mark.django_db
def test_un_modulo_fuera_del_ambito_queda_fuera(multi, casa, client):
    pareja = _miembro(casa, "pareja@x.mx", Membership.Role.ADULT,
                      scopes=["finance"])

    assert _sesion(client, pareja).get("/vehiculos/").status_code == 403


@pytest.mark.django_db
def test_sin_ambitos_se_ve_todo_lo_que_el_rol_permita(multi, casa, client):
    pareja = _miembro(casa, "pareja@x.mx", Membership.Role.ADULT)
    sesion = _sesion(client, pareja)

    assert sesion.get("/dinero/").status_code == 200
    assert sesion.get("/vehiculos/").status_code == 200


@pytest.mark.django_db
def test_al_titular_no_se_le_pueden_poner_ambitos(multi, casa):
    """Un hogar que nadie puede ver entero no se puede administrar."""
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER, scopes=["tasks"])

    assert yo.sees_everything
    assert yo.sees("finance")


# --- El acceso profesional caduca solo --------------------------------------


@pytest.mark.django_db
def test_el_contador_ve_solo_impuestos_y_no_escribe(multi, casa, client):
    contador = _miembro(casa, "contador@x.mx", Membership.Role.PROFESSIONAL,
                        scopes=["taxes"], caduca=HOY + dt.timedelta(days=60))
    sesion = _sesion(client, contador)

    assert sesion.get("/impuestos/").status_code == 200
    assert sesion.get("/dinero/").status_code == 403
    assert sesion.post("/impuestos/deducible/", {}).status_code == 403


@pytest.mark.django_db
def test_pasada_la_fecha_el_acceso_se_cierra_solo(multi, casa, client):
    """Nadie se acuerda de quitar al contador en mayo."""
    contador = _miembro(casa, "contador@x.mx", Membership.Role.PROFESSIONAL,
                        scopes=["taxes"], caduca=HOY - dt.timedelta(days=1))

    assert contador.is_expired
    assert not contador.is_live
    assert _sesion(client, contador).get("/impuestos/").status_code == 403


@pytest.mark.django_db
def test_una_invitacion_sin_aceptar_no_abre_nada(multi, casa, client):
    pendiente = _miembro(casa, "nadie@x.mx", Membership.Role.ADULT,
                         acepta=False)

    assert _sesion(client, pendiente).get("/").status_code == 403


# --- No enseñar lo que no se puede abrir ------------------------------------


@pytest.mark.django_db
def test_el_menu_no_ofrece_puertas_cerradas(multi, casa, client):
    """Un título como «Tarjeta ****9876» es una fuga aunque no pueda entrar."""
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER,
                    scopes=["tasks"])
    html = _sesion(client, hijo).get("/").content.decode()

    assert "/dinero/" not in html
    assert reverse("core:owed") not in html


@pytest.mark.django_db
def test_el_tablero_no_muestra_huecos_de_lo_que_no_ve(multi, casa, client):
    from lares.core.models import Account

    Account.objects.create(household=casa, name="Tarjeta secreta",
                           type=Account.Type.ASSET)
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER,
                    scopes=["tasks"])

    contexto = _sesion(client, hijo).get("/").context
    assert all(not f.check.startswith("finance.")
               for f in contexto["findings"])


@pytest.mark.django_db
def test_quien_ve_todo_sigue_viendo_todo_el_menu(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)
    html = _sesion(client, yo).get("/").content.decode()

    assert "/dinero/" in html


# --- Varios hogares ---------------------------------------------------------


@pytest.mark.django_db
def test_se_puede_entrar_a_dos_hogares_con_roles_distintos(multi, casa, client):
    """«Administro también la casa de mis padres» es el caso real."""
    otra = Household.objects.create(name="Casa de mis padres", slug="padres")
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)
    from django.utils import timezone

    Membership.objects.create(household=otra, user=yo.user,
                              role=Membership.Role.VIEWER,
                              accepted_at=timezone.now())
    sesion = _sesion(client, yo)

    assert sesion.get(f"/hogar/cambiar/{otra.pk}/").status_code == 302
    assert sesion.get("/").context["current_household"] == otra


@pytest.mark.django_db
def test_no_se_puede_saltar_a_un_hogar_ajeno(multi, casa, client):
    """El hogar activo nunca se acepta de un parámetro sin comprobar."""
    ajena = Household.objects.create(name="Casa ajena", slug="ajena")
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    assert _sesion(client, yo).get(f"/hogar/cambiar/{ajena.pk}/") \
        .status_code == 404


@pytest.mark.django_db
def test_con_un_solo_hogar_no_se_ofrece_el_selector(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    assert _sesion(client, yo).get("/").context["households"] == []


# --- Invitar ----------------------------------------------------------------


@pytest.mark.django_db
def test_invitar_crea_la_persona_y_un_enlace_de_un_solo_uso(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)
    sesion = _sesion(client, yo)

    respuesta = sesion.post("/hogar/invitar/", {
        "email": "pareja@x.mx", "display_name": "Mariana",
        "role": Membership.Role.ADULT, "scopes": ["finance", "property"],
    }, follow=True)

    nueva = Membership.objects.get(user__email="pareja@x.mx")
    assert respuesta.status_code == 200
    assert nueva.scopes == ["finance", "property"]
    assert nueva.invite_token
    assert not nueva.is_accepted
    assert not nueva.user.has_usable_password()


@pytest.mark.django_db
def test_aceptar_la_invitacion_pone_contrasena_y_entra(multi, casa, client):
    nuevo = _miembro(casa, "pareja@x.mx", Membership.Role.ADULT, acepta=False)
    token = nuevo.new_invite()

    respuesta = client.post(f"/invitacion/{token}/",
                            {"password1": "unaclavelarga",
                             "password2": "unaclavelarga"})
    nuevo.refresh_from_db()

    assert respuesta.status_code == 302
    assert nuevo.is_accepted
    assert nuevo.user.check_password("unaclavelarga")


@pytest.mark.django_db
def test_el_enlace_no_sirve_dos_veces(multi, casa, client):
    """Un enlace que sigue valiendo acaba reenviado en un chat familiar."""
    nuevo = _miembro(casa, "pareja@x.mx", Membership.Role.ADULT, acepta=False)
    token = nuevo.new_invite()
    client.post(f"/invitacion/{token}/", {"password1": "unaclavelarga",
                                          "password2": "unaclavelarga"})

    assert client.get(f"/invitacion/{token}/").status_code == 404


@pytest.mark.django_db
def test_un_token_inventado_no_abre_nada(multi, casa, client):
    assert client.get("/invitacion/loquesea/").status_code == 404


@pytest.mark.django_db
def test_un_profesional_sin_fecha_no_se_puede_guardar(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)

    respuesta = _sesion(client, yo).post("/hogar/invitar/", {
        "email": "contador@x.mx", "role": Membership.Role.PROFESSIONAL,
        "scopes": ["taxes"],
    })

    assert respuesta.status_code == 200
    assert "expires_on" in respuesta.context["form"].errors


@pytest.mark.django_db
def test_al_titular_no_se_le_quita_el_acceso(multi, casa, client):
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)
    otro = _miembro(casa, "otro@x.mx", Membership.Role.OWNER)

    _sesion(client, yo).get(f"/hogar/miembro/{otro.pk}/quitar/")
    assert Membership.objects.filter(pk=otro.pk).exists()


@pytest.mark.django_db
def test_quitar_a_alguien_no_borra_lo_que_registro(multi, casa, client):
    from lares.core.models import Account

    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER)
    Account.objects.create(household=casa, name="Su cuenta",
                           type=Account.Type.ASSET)

    _sesion(client, yo).get(f"/hogar/miembro/{hijo.pk}/quitar/")

    assert not Membership.objects.filter(pk=hijo.pk).exists()
    assert Account.all_objects.filter(household=casa).count() == 1


# --- El modo de un solo hogar no cambia -------------------------------------


@pytest.mark.django_db
def test_en_modo_single_no_se_pide_membresia(settings, casa, client,
                                              django_user_model):
    """Quien instala esto para sí mismo no debería topar con permisos."""
    settings.TENANCY_MODE = "single"
    user = django_user_model.objects.create_user(
        username="solo@x.mx", email="solo@x.mx", password="x")
    client.force_login(user)

    assert client.get("/dinero/").status_code == 200


# --- Que no se escape una pantalla sin clasificar ---------------------------

# Las del núcleo que son del armazón y las ve cualquier miembro del hogar: el
# tablero, la bandeja, los documentos, la búsqueda, las cosas que se poseen.
# Todo lo demás de `core:` tiene que estar en `AMBITO_DE_RUTA`, porque `core:`
# publica pantallas de dominios muy distintos y la del dinero no la puede ver
# el hijo de dieciséis.
ARMAZON = {
    "core:dashboard", "core:search", "core:add", "core:onboarding",
    "core:holdings", "core:documents", "core:document-new",
    "core:document-preview", "core:inbox", "core:inbox-item",
    "core:inbox-share", "core:inbox-apply", "core:inbox-discard",
    "core:inbox-upload", "core:inbox-reclassify",
    "core:resource-new", "core:resource-detail", "core:resource-edit",
    "core:resource-dispose", "core:resource-keep", "core:resource-lend",
    "core:location-new", "core:obligation-done", "core:obligation-waive",
    "core:obligation-ics", "core:calendar-feed", "core:manifest",
    "core:service-worker", "core:login", "core:logout",
    # Tu propia cuenta no es un dominio del hogar: la usa cualquiera, y quien
    # tenga el dinero restringido tiene que poder cambiar su clave igual.
    "core:password-change",
    # El alta rápida y el buscador sirven a doce desplegables de ámbitos
    # distintos, así que no tienen uno propio: cada llamada mide el de lo
    # que se crea o se lista.
    "core:quick-add",
    "core:options",
    "core:invite-accept", "core:household-switch",
    "core:document-edit", "core:inbox-file", "core:inbox-review",
    "core:inbox-restore", "core:inbox-reclassify-all",
    "core:resource-restore", "core:resource-return", "core:resource-verify",
    "core:resource-care",
    "core:shared", "core:shared-vcf",
    "core:health", "core:health-db",
    "core:succession-package", "core:succession-download",
    "core:succession-json", "core:succession-document",
}


def _rutas_del_nucleo() -> set:
    from django.urls import get_resolver

    resolver = get_resolver()
    nombres = set()
    for clave, (_, _, _) in resolver.reverse_dict.items():
        if isinstance(clave, str):
            nombres.add(clave)
    espacio = resolver.namespace_dict.get("core")
    if espacio:
        nombres |= {f"core:{n}" for n in espacio[1].reverse_dict
                    if isinstance(n, str)}
    return {n for n in nombres if n.startswith("core:")}


@pytest.mark.django_db
def test_toda_pantalla_del_nucleo_esta_clasificada():
    """Una pantalla nueva del núcleo obliga a decidir a qué ámbito pertenece.

    Sin esto, alguien añade `core:saldos-de-todos` y por omisión la ve el hijo.
    """
    from lares.core.permissions import AMBITO_DE_API, AMBITO_DE_RUTA

    conocidas = set(AMBITO_DE_RUTA) | set(AMBITO_DE_API) | ARMAZON
    sin_clasificar = sorted(_rutas_del_nucleo() - conocidas)

    assert not sin_clasificar, (
        f"Pantallas del núcleo sin ámbito: {sin_clasificar}. "
        "Añádelas a AMBITO_DE_RUTA o, si son del armazón, a ARMAZON."
    )


@pytest.mark.django_db
def test_las_pantallas_de_dinero_del_nucleo_piden_el_ambito(multi, casa,
                                                             client):
    """Viven en `core:` pero son dinero: la clasificación tiene que valer."""
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])
    sesion = _sesion(client, hijo)

    for url in ("/se-debe/", "/recurrentes/", "/gastos/nuevo/",
                "/ingresos/nuevo/", "/traspasos/nuevo/", "/cuentas/nueva/"):
        assert sesion.get(url).status_code == 403, url


@pytest.mark.django_db
def test_el_armazon_lo_ve_cualquiera(multi, casa, client):
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])
    sesion = _sesion(client, hijo)

    for url in ("/", "/bandeja/", "/documentos/", "/buscar/"):
        assert sesion.get(url).status_code == 200, url


# --- Modo de un solo hogar --------------------------------------------------


@pytest.mark.django_db
def test_en_single_se_puede_invitar_sin_tener_membresia(settings, casa, client,
                                                         django_user_model):
    """Y al hacerlo, quien instaló esto queda como titular.

    Si no, al pasar a multiusuario se quedaría fuera de su propia casa.
    """
    settings.TENANCY_MODE = "single"
    user = django_user_model.objects.create_user(
        username="solo@x.mx", email="solo@x.mx", password="x")
    client.force_login(user)
    assert not Membership.objects.filter(user=user).exists()

    assert client.get("/hogar/invitar/").status_code == 200
    mia = Membership.objects.get(user=user)
    assert mia.role == Membership.Role.OWNER
    assert mia.is_live


# --- La API se mide igual que las pantallas ---------------------------------


@pytest.mark.django_db
def test_la_api_no_es_una_puerta_de_atras(multi, casa, client):
    """Acepta la sesión del navegador para leer, así que se mide igual.

    Saltársela por ser un endpoint «sin login» dejaba a un miembro con ámbitos
    limitados sacar por `/api/v1/` lo que la pantalla le negaba.
    """
    from lares.core.models import Account

    Account.objects.create(household=casa, name="Tarjeta",
                           type=Account.Type.LIABILITY)
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])
    sesion = _sesion(client, hijo)

    # El armazón sí: la agenda y los documentos no son el dinero.
    assert sesion.get("/api/v1/agenda").status_code == 200
    # Los webhooks son administración.
    assert sesion.get("/api/v1/webhooks").status_code == 403


@pytest.mark.django_db
def test_solo_lectura_no_escribe_por_la_api(multi, casa, client):
    invitado = _miembro(casa, "invitado@x.mx", Membership.Role.VIEWER)

    respuesta = _sesion(client, invitado).post(
        "/api/v1/obligations/00000000-0000-0000-0000-000000000000/complete")
    assert respuesta.status_code == 403


@pytest.mark.django_db
def test_el_feed_del_calendario_sigue_abierto_con_sesion(multi, casa, client):
    """Lo valida su propio token; medirlo contra ámbitos lo rompería."""
    token = casa.rotate_calendar_token()
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])

    assert _sesion(client, hijo).get(f"/calendario/{token}.ics") \
        .status_code == 200


@pytest.mark.django_db
def test_sin_el_ambito_de_personas_no_se_exporta_la_agenda(multi, casa, client):
    """Un vCard saca todos los contactos de golpe."""
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])

    assert _sesion(client, hijo).get("/contactos/todos.vcf").status_code == 403


# --- Los datos del hogar ----------------------------------------------------


@pytest.mark.django_db
def test_el_nombre_del_hogar_se_cambia_desde_la_pantalla(multi, casa, client):
    """Sale en los correos y en el paquete de sucesión: una errata se corrige."""
    yo = _miembro(casa, "yo@x.mx", Membership.Role.OWNER)
    sesion = _sesion(client, yo)

    assert sesion.get("/hogar/datos/").status_code == 200
    respuesta = sesion.post("/hogar/datos/", {
        "name": "Casa de los Candelas", "country": "mx",
        "subdivision": "MX-JAL", "timezone": "America/Mexico_City",
        "currency": "MXN",
    })

    casa.refresh_from_db()
    assert respuesta.status_code == 302
    assert casa.name == "Casa de los Candelas"
    # El país se guarda en mayúsculas o los packs dejan de encontrarse.
    assert casa.country == "MX"


@pytest.mark.django_db
def test_los_datos_del_hogar_son_de_quien_administra(multi, casa, client):
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.ADULT)

    assert _sesion(client, hijo).get("/hogar/datos/").status_code == 403


# --- Los títulos también cuentan de más -------------------------------------


def _vencimiento_de_dinero(casa):
    """Una obligación del módulo de dinero, con un título que ya dice de más."""
    import datetime as _dt

    from lares.core.models import Obligation
    from lares.core.scoping import use_household

    with use_household(casa):
        return Obligation.objects.create(
            household=casa, dedupe_key="tarjeta-1", source="finance.card_payment",
            title="Tarjeta ****9876, pago mínimo",
            due_on=HOY + _dt.timedelta(days=3), amount=4200,
        )


@pytest.mark.django_db
def test_el_tablero_no_enseña_vencimientos_de_lo_que_no_ve(multi, casa, client):
    _vencimiento_de_dinero(casa)
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])

    html = _sesion(client, hijo).get("/").content.decode()

    assert "9876" not in html


@pytest.mark.django_db
def test_el_reparto_tampoco(multi, casa, client):
    """Es la pantalla que lista lo de todo el mundo: ahí pesa más."""
    _vencimiento_de_dinero(casa)
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER,
                    scopes=["tasks", "people"])

    html = _sesion(client, hijo).get("/reparto/").content.decode()

    assert "9876" not in html


@pytest.mark.django_db
def test_la_api_devuelve_lo_mismo_que_la_pantalla(multi, casa, client):
    """Aceptar la sesión y no medir los ámbitos ya fue una puerta de atrás una vez."""
    import json

    _vencimiento_de_dinero(casa)
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])
    sesion = _sesion(client, hijo)

    agenda = json.loads(sesion.get("/api/v1/agenda").content)
    titulos = [o["title"] for clave in ("overdue", "this_week", "later")
               for o in agenda[clave]]

    assert all("9876" not in t for t in titulos)
    assert agenda["total_amount"] == 0


@pytest.mark.django_db
def test_quien_ve_el_dinero_lo_sigue_viendo(multi, casa, client):
    _vencimiento_de_dinero(casa)
    pareja = _miembro(casa, "pareja@x.mx", Membership.Role.ADULT,
                      scopes=["finance", "people"])
    sesion = _sesion(client, pareja)

    assert "9876" in sesion.get("/").content.decode()
    assert "9876" in sesion.get("/reparto/").content.decode()


@pytest.mark.django_db
def test_un_vencimiento_de_un_pack_es_del_modulo_de_su_recurso(casa):
    """El refrendo del coche es de los coches, aunque la regla venga de un YAML."""
    import datetime as _dt

    from lares.core.models import Obligation
    from lares.core.permissions import scope_of_obligation
    from lares.core.scoping import use_household

    with use_household(casa):
        refrendo = Obligation.objects.create(
            household=casa, dedupe_key="refrendo-1", source="packs.vehicle",
            title="Refrendo", due_on=HOY + _dt.timedelta(days=5),
        )

    assert scope_of_obligation(refrendo) == "vehicles"


# --- El alta rápida no es una puerta de atrás -------------------------------


@pytest.mark.django_db
def test_el_alta_rapida_mide_el_ambito_de_lo_que_se_crea(multi, casa, client):
    """Crear una cuenta desde un desplegable sigue siendo crear una cuenta.

    Es el riesgo de todo atajo: la puerta de la pantalla cerrada y la de al
    lado abierta. Quien tiene el dinero restringido no crea cuentas por aquí.
    """
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])
    sesion = _sesion(client, hijo)

    assert sesion.get("/rapido/account/").status_code == 403
    assert sesion.post("/rapido/account/",
                       {"name": "Cuenta secreta", "type": "asset",
                        "currency": "MXN"}).status_code == 403
    from lares.core.models import Account
    assert not Account.all_objects.filter(name="Cuenta secreta").exists()


@pytest.mark.django_db
def test_con_el_ambito_concedido_el_alta_rapida_si_crea(multi, casa, client):
    pareja = _miembro(casa, "pareja@x.mx", Membership.Role.ADULT,
                      scopes=["finance"])
    sesion = _sesion(client, pareja)

    respuesta = sesion.post("/rapido/account/",
                            {"name": "Ahorro", "type": "asset",
                             "currency": "MXN"})

    assert respuesta.status_code == 200
    assert respuesta.json()["label"] == "Ahorro"


@pytest.mark.django_db
def test_quien_solo_mira_no_crea_por_el_atajo(multi, casa, client):
    invitado = _miembro(casa, "invitado@x.mx", Membership.Role.VIEWER)

    assert _sesion(client, invitado).post(
        "/rapido/party/", {"kind": "person", "name": "Alguien"}
    ).status_code == 403


@pytest.mark.django_db
def test_el_buscador_tampoco_lista_lo_que_no_se_puede_ver(multi, casa, client):
    """Devolver los nombres de las cuentas es una fuga aunque la pantalla de
    cuentas esté cerrada."""
    hijo = _miembro(casa, "hijo@x.mx", Membership.Role.MEMBER, scopes=["tasks"])

    assert _sesion(client, hijo).get("/opciones/account/").status_code == 403


@pytest.mark.django_db
def test_quien_solo_mira_si_puede_buscar(multi, casa, client):
    """Mirar no es escribir: se le niega crear, no consultar."""
    invitado = _miembro(casa, "invitado@x.mx", Membership.Role.VIEWER)
    sesion = _sesion(client, invitado)

    assert sesion.get("/opciones/party/").status_code == 200
    assert sesion.post("/rapido/party/",
                       {"kind": "person", "name": "X"}).status_code == 403
