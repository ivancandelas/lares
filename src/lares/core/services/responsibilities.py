"""Quién se encarga de qué.

En un hogar de dos adultos, la mitad de las discusiones no son sobre si algo se
hizo, sino sobre **de quién era**. El sistema ya sabe lo que hay que hacer y
cuándo; lo que faltaba es de quién es.

Dos niveles, y ninguno guarda una copia de nada:

  - **Lo permanente**: quien se encarga de una cosa. Es una arista del grafo
    (`cared_by`), no una columna, porque es un papel que una persona juega
    frente a algo -igual que "propietario" o "asegurado por"- y porque tiene
    historia: quien se encargaba de la casa en 2025 se puede seguir leyendo.
  - **Lo puntual**: `Obligation.assigned_to`, para cuando esta vez le toca a
    otro.

**La obligacion no hereda una copia del responsable.** Se pregunta: primero su
`assigned_to`, y si no lo tiene, quien se encarga de su sujeto. Copiarlo al
materializar crearia dos verdades que se separan en cuanto alguien cambie de
quien se encarga del coche, y entonces habria que decidir si pisar o no una
asignacion manual. Preguntando no hay nada que decidir.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.contenttypes.models import ContentType

from ..models import Link, Obligation, Party

CARED_BY = "cared_by"


# ---------------------------------------------------------------------------
# Leer
# ---------------------------------------------------------------------------


def responsible_of(entity):
    """Quién se encarga de esto ahora mismo. None si no se ha dicho."""
    if entity is None:
        return None
    link = _live_link(entity)
    return link.target if link else None


def _live_link(entity):
    ctype = ContentType.objects.get_for_model(entity.__class__)
    return Link.objects.filter(
        role=CARED_BY, source_type=ctype, source_id=entity.pk,
        valid_to__isnull=True,
    ).first()


def responsible_map(household) -> dict:
    """`{(content_type_id, uuid): Party}` de todo el hogar, en dos consultas.

    Existe por el tablero: resolver el responsable fila a fila seria un N+1 que
    crece con los datos, que es exactamente lo que vigila
    `test_el_tablero_no_crece_con_los_datos`. Las aristas de este tipo son
    pocas -una por cosa- asi que traerlas todas sale mas barato que preguntar.
    """
    enlaces = list(Link.objects.filter(role=CARED_BY, valid_to__isnull=True))
    if not enlaces:
        return {}
    personas = {
        p.pk: p for p in
        Party.objects.filter(pk__in={e.target_id for e in enlaces})
    }
    return {
        (e.source_type_id, e.source_id): personas[e.target_id]
        for e in enlaces if e.target_id in personas
    }


def annotate(obligaciones, mapa: dict) -> list:
    """Pone `responsible` en cada obligación, sin una consulta por fila.

    Gana lo puntual sobre lo permanente: si esta vez le toca a otro, es que le
    toca a otro.
    """
    salida = []
    for o in obligaciones:
        o.responsible = o.assigned_to or mapa.get((o.subject_type_id, o.subject_id))
        salida.append(o)
    return salida


def split(household) -> dict:
    """El reparto: qué lleva cada quien, y qué no lleva nadie.

    Lo último es la mitad del valor de esta pantalla. Una obligación de la que
    no se encarga nadie no es que esté sin asignar: es la que se pasa.
    """
    hoy = dt.date.today()
    mapa = responsible_map(household)

    pendientes = annotate(
        list(Obligation.objects.filter(
            status__in=[Obligation.Status.PENDING, Obligation.Status.OVERDUE],
        ).select_related("assigned_to", "counterparty")),
        mapa,
    )

    cosas = _cosas_por_responsable(mapa)

    por_persona, huerfanas = {}, []
    for o in pendientes:
        if o.responsible is None:
            huerfanas.append(o)
            continue
        por_persona.setdefault(o.responsible.pk, []).append(o)

    gente = {p.pk: p for p in mapa.values()}
    gente.update({o.responsible.pk: o.responsible
                  for o in pendientes if o.responsible})

    reparto = []
    for pk, persona in gente.items():
        suyas = por_persona.get(pk, [])
        reparto.append({
            "party": persona,
            "cosas": cosas.get(pk, []),
            "obligaciones": sorted(suyas, key=lambda o: o.due_on),
            "vencidas": [o for o in suyas if o.due_on < hoy],
            "importe": sum(o.amount or 0 for o in suyas),
        })
    # Quien más lleva encima, primero: es la pregunta que trae a esta pantalla.
    reparto.sort(key=lambda r: (-len(r["obligaciones"]), r["party"].name))

    return {
        "reparto": reparto,
        "huerfanas": sorted(huerfanas, key=lambda o: o.due_on),
        "sin_dueno": _cosas_sin_responsable(mapa),
    }


def _cosas_por_responsable(mapa: dict) -> dict:
    """Las cosas a cargo de cada quien, resueltas a su modelo concreto."""
    from ..models.resource import Resource

    salida = {}
    recursos = {
        r.pk: r for r in
        Resource.objects.filter(status=Resource.Status.ACTIVE)
    }
    for (_, source_id), persona in mapa.items():
        recurso = recursos.get(source_id)
        if recurso:
            salida.setdefault(persona.pk, []).append(recurso)
    return salida


def _cosas_sin_responsable(mapa: dict) -> list:
    from ..models.resource import Resource

    con_dueno = {source_id for _, source_id in mapa}
    return [r for r in Resource.objects.filter(status=Resource.Status.ACTIVE)
            if r.pk not in con_dueno]


# ---------------------------------------------------------------------------
# Escribir
# ---------------------------------------------------------------------------


def set_responsible(household, entity, party, on_date: dt.date | None = None):
    """Pone a alguien al frente de algo. `party=None` deja la cosa sin dueño.

    La arista anterior no se borra: se cierra. Quien se encargaba antes es
    historial, y el historial es la mitad de por qué esto es un grafo.
    """
    on_date = on_date or dt.date.today()
    ctype = ContentType.objects.get_for_model(entity.__class__)

    actual = _live_link(entity)
    if actual and party and actual.target_id == party.pk:
        return actual
    if actual:
        actual.valid_to = on_date
        actual.save(update_fields=["valid_to", "updated_at"])
    if party is None:
        return None

    return Link.objects.create(
        household=household,
        source_type=ctype, source_id=entity.pk, role=CARED_BY,
        target_type=ContentType.objects.get_for_model(Party),
        target_id=party.pk, valid_from=on_date,
    )
