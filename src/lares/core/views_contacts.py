"""Contactos: etiquetas, exportacion y enlaces compartidos."""

from __future__ import annotations

import datetime as dt

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import INPUT
from .models import ContactPoint, Party, Share, Tag
from .models.tagging import tagged, tags_of
from .services import vcard


def contacts(request):
    """El directorio: personas, organizaciones y sus etiquetas.

    Es la unica pantalla de personas que hay. Tener una lista "de personas" y
    otra "de contactos" obligaba a recordar en cual estaba cada dato, que es lo
    contrario de lo que promete el sistema.
    """
    personas = list(Party.objects.filter(kind=Party.Kind.PERSON))
    organizaciones = list(Party.objects.filter(kind=Party.Kind.ORGANIZATION))

    grupos = []
    con_etiqueta = set()
    for tag in Tag.objects.all():
        gente = [p for p in tagged(tag, Party) if p.kind == Party.Kind.PERSON]
        if gente:
            grupos.append({"tag": tag, "people": gente})
            con_etiqueta.update(p.pk for p in gente)

    return render(request, "core/contacts.html", {
        "grupos": grupos,
        "sueltos": [p for p in personas if p.pk not in con_etiqueta],
        "organizaciones": organizaciones,
        "compartidos": Share.objects.filter(revoked_at__isnull=True),
    })


def contact_points(request, pk):
    """Teléfonos y correos de alguien, para que otros puedan comunicarse."""
    party = get_object_or_404(Party, pk=pk)

    if request.method == "POST" and request.POST.get("value"):
        ContactPoint.objects.create(
            household=request.household, party=party,
            channel=request.POST.get("channel") or ContactPoint.Channel.PHONE,
            label=request.POST.get("label", "")[:60],
            value=request.POST["value"][:400],
        )
        messages.success(request, "Añadido.")
        return redirect("core:party-detail", pk=party.pk)

    return render(request, "core/contact_points.html", {
        "party": party,
        "canales": ContactPoint.Channel.choices,
    })


def contact_point_delete(request, pk):
    punto = get_object_or_404(ContactPoint, pk=pk)
    party_pk = punto.party_id
    punto.delete()
    messages.success(request, "Eliminado.")
    return redirect("core:party-detail", pk=party_pk)


# ---------------------------------------------------------------------------
# Exportacion
# ---------------------------------------------------------------------------


def _vcf(contenido: str, nombre: str) -> HttpResponse:
    respuesta = HttpResponse(contenido, content_type="text/vcard; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}.vcf"'
    return respuesta


def party_vcard(request, pk):
    party = get_object_or_404(Party, pk=pk)
    return _vcf(vcard.export([party]), party.name.replace(" ", "-").lower())


def tag_vcard(request, slug):
    tag = get_object_or_404(Tag, slug=slug)
    return _vcf(vcard.export(tagged(tag, Party)), tag.slug)


def all_vcards(request):
    return _vcf(vcard.export(Party.objects.all()), "contactos")


# ---------------------------------------------------------------------------
# Compartir
# ---------------------------------------------------------------------------


class ShareForm(forms.ModelForm):
    class Meta:
        model = Share
        fields = ["label", "target", "note", "expires_on"]
        labels = {
            "label": "Cómo lo llamas",
            "target": "Qué etiqueta compartes",
            "note": "Para quién es",
            "expires_on": "Caduca el",
        }
        help_texts = {
            "expires_on": "Un enlace sin fecha acaba siendo permanente por olvido.",
        }

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self.fields["target"] = forms.ChoiceField(
            choices=[(t.slug, t.name) for t in Tag.objects.all()],
            label="Qué etiqueta compartes",
        )
        self.fields["expires_on"].widget.input_type = "date"
        self.fields["expires_on"].initial = dt.date.today() + dt.timedelta(days=90)
        for campo in self.fields.values():
            campo.widget.attrs.setdefault("class", INPUT)


def share_new(request):
    form = ShareForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        share = form.save(commit=False)
        share.household = request.household
        share.kind = Share.Kind.CONTACTS
        share.save()
        messages.success(request, "Enlace creado. Cópialo y mándalo.")
        return redirect("core:shares")

    return render(request, "core/form.html", {
        "form": form, "title": "Compartir una etiqueta de contactos",
        "submit": "Crear enlace", "cancel_url": "core:shares",
    })


def shares(request):
    """Qué tienes compartido, con quién y si alguien lo ha abierto."""
    return render(request, "core/shares.html", {
        "shares": Share.objects.all(),
    })


def share_revoke(request, pk):
    from django.utils import timezone

    share = get_object_or_404(Share, pk=pk)
    share.revoked_at = timezone.now()
    share.save(update_fields=["revoked_at", "updated_at"])
    messages.success(request, f"«{share.label}» dejó de funcionar.")
    return redirect("core:shares")


@login_not_required
def shared_view(request, token):
    """Lo que ve quien recibe el enlace. Solo lectura, y solo lo compartido."""
    share = Share.all_objects.filter(token=token).first()
    if not share or not share.is_live:
        raise Http404("Ese enlace no existe o dejó de funcionar.")

    tag = Tag.all_objects.filter(household=share.household,
                                 slug=share.target).first()
    gente = []
    if tag:
        from .scoping import use_household

        with use_household(share.household):
            gente = tagged(tag, Party)

    share.touch()
    return render(request, "core/shared.html", {
        "share": share, "tag": tag, "people": gente,
        "hogar": share.household,
    })


@login_not_required
def shared_vcard(request, token):
    share = Share.all_objects.filter(token=token).first()
    if not share or not share.is_live:
        raise Http404("Ese enlace no existe o dejó de funcionar.")

    from .scoping import use_household

    with use_household(share.household):
        tag = Tag.objects.filter(slug=share.target).first()
        gente = tagged(tag, Party) if tag else []
        contenido = vcard.export(gente)

    share.touch()
    return _vcf(contenido, share.target or "contactos")


def _tags_display(party) -> list:
    return tags_of(party)
