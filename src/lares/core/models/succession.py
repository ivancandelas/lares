"""Sucesion y emergencia: quien recibe que si dejas de entrar.

Es una de las razones reales por las que alguien instala esto. Si al titular le
pasa algo, su familia necesita saber que polizas existen, donde estan las
escrituras, que se paga cada mes y a quien llamar. Ese conocimiento suele vivir
en una sola cabeza, y es justo la que falta ese dia.

El mecanismo es un interruptor de hombre muerto, con tres decisiones que lo
hacen utilizable y no peligroso:

  1. **Se avisa antes de liberar.** El silencio no libera nada por si solo:
     abre una ventana de gracia y manda avisos. Un viaje largo no puede
     acabar con los datos de alguien en el correo de su cunado.
  2. **Volver lo cierra.** En cuanto el titular vuelve a entrar, lo avisado se
     rearma y lo liberado se revoca. Quien vuelve esta vivo.
  3. **El paquete es curado, no el sistema entero.** Se elige que secciones
     lleva. Heredar el acceso completo no es sucesion, es una copia de la
     llave de casa.

Lo que se libera es de solo lectura y deja rastro: cada apertura se cuenta.
"""

import datetime as dt
import secrets

from django.db import models

from .base import HouseholdScopedModel


class EmergencyContact(HouseholdScopedModel):
    """Alguien a quien se le libera un paquete si el titular deja de entrar."""

    class State(models.TextChoices):
        ARMED = "armed", "Armado"
        WARNED = "warned", "Avisado"
        RELEASED = "released", "Liberado"
        OFF = "off", "Desactivado"

    # Si ya esta en contactos se referencia; si no, basta el nombre. Obligar a
    # darlo de alta antes de poder nombrarlo es la clase de friccion por la que
    # esto se queda sin configurar.
    party = models.ForeignKey(
        "core.Party", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="emergency_roles",
    )
    name = models.CharField("cómo se llama", max_length=160)
    email = models.EmailField("correo", blank=True)
    relationship = models.CharField("qué es tuyo", max_length=80, blank=True)

    # Que secciones lleva el paquete. Vacio significa todas, como en los
    # ambitos de una membresia.
    sections = models.JSONField("qué incluye", default=list, blank=True)
    note = models.TextField("qué quieres que sepa", blank=True)

    quiet_days = models.PositiveSmallIntegerField("si no entras en", default=60)
    grace_days = models.PositiveSmallIntegerField("avisar y esperar", default=7)

    state = models.CharField(max_length=12, choices=State.choices,
                             default=State.ARMED)
    warned_on = models.DateField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    token = models.CharField(max_length=43, blank=True, db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    hits = models.PositiveIntegerField("veces abierto", default=0)

    class Meta:
        ordering = ["name"]
        verbose_name = "contacto de emergencia"
        verbose_name_plural = "contactos de emergencia"

    def __str__(self):
        return self.name

    # -- Vigencia ------------------------------------------------------------

    @property
    def is_live(self) -> bool:
        """Si el enlace del paquete funciona ahora mismo."""
        return self.state == self.State.RELEASED and bool(self.token)

    @property
    def releases_on(self) -> dt.date | None:
        """Cuándo se libera, si ya se avisó."""
        if self.state != self.State.WARNED or not self.warned_on:
            return None
        return self.warned_on + dt.timedelta(days=self.grace_days)

    @property
    def state_label(self) -> str:
        if self.state == self.State.OFF:
            return "desactivado"
        if self.state == self.State.RELEASED:
            return f"liberado el {self.released_at:%d/%m/%Y}"
        if self.state == self.State.WARNED:
            return f"avisado, se libera el {self.releases_on:%d/%m/%Y}"
        return f"armado: {self.quiet_days} días sin entrar"

    @property
    def section_labels(self) -> list:
        """Qué lleva su paquete, con los nombres que se leen."""
        from ..services.succession import SECCIONES, secciones_de

        etiquetas = dict(SECCIONES)
        return [etiquetas[clave] for clave in secciones_de(self)]

    @property
    def who(self) -> str:
        return self.party.name if self.party_id else self.name

    @property
    def where(self) -> str:
        """A dónde le llega el enlace.

        Manda el correo escrito aqui: si alguien se molesto en ponerlo teniendo
        la ficha delante, es porque quiere ese y no el otro. Si no hay, se usa
        el de la ficha.

        Se consulta con `all_objects` a proposito: esto lo llama una tarea de
        fondo, y depender del hogar activo del hilo lo dejaria sin destinatario
        justo el dia que hace falta.
        """
        if self.email:
            return self.email
        if self.party_id:
            from .party import ContactPoint

            punto = (ContactPoint.all_objects
                     .filter(party_id=self.party_id,
                             channel=ContactPoint.Channel.EMAIL)
                     .order_by("-is_primary").first())
            if punto:
                return punto.value
        return ""

    # -- Acciones ------------------------------------------------------------

    def open_link(self) -> str:
        """Genera el enlace del paquete. Solo al liberar."""
        self.token = secrets.token_urlsafe(32)
        return self.token

    def touch(self):
        from django.utils import timezone

        type(self).all_objects.filter(pk=self.pk).update(
            hits=models.F("hits") + 1, last_seen_at=timezone.now()
        )
