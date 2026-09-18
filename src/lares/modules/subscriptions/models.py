"""Lo que tienes contratado.

Netflix, Disney+, un VPS, el iCloud de tu hijo, el gimnasio, el dominio. Suman
sin que nadie lo note y son lo que mas facil se queda pagado de mas: nadie
cancela lo que no recuerda tener.

Tres ejes que casi ningun gestor separa y que aqui deciden lo que el sistema
puede hacer por ti:

    quien paga        tu, siempre. Por eso vive en tu dinero.
    de quien es       puede no ser tuya: la cuenta de Apple de tu hijo es suya.
    quien accede      tuya, compartida, o de otro.

En una cuenta tuya el sistema puede decir "cancelala". En la de tu hijo solo
puede decir "esto lo estas pagando tu, y subio de precio en marzo".
"""

from decimal import Decimal

from django.db import models

from lares.core.models import Resource

CICLOS_AL_ANO = {"monthly": 12, "quarterly": 4, "semiannual": 2, "yearly": 1,
                 "weekly": 52}


class Subscription(Resource):
    resource_kind = "subscription"

    class Cycle(models.TextChoices):
        WEEKLY = "weekly", "Cada semana"
        MONTHLY = "monthly", "Cada mes"
        QUARTERLY = "quarterly", "Cada tres meses"
        SEMIANNUAL = "semiannual", "Cada seis meses"
        YEARLY = "yearly", "Cada año"

    class Access(models.TextChoices):
        MINE = "mine", "La cuenta es mía"
        SHARED = "shared", "Compartida en la familia"
        THEIRS = "theirs", "Es de otra persona, yo solo la pago"

    class Kind(models.TextChoices):
        STREAMING = "streaming", "Streaming y entretenimiento"
        SOFTWARE = "software", "Software y apps"
        HOSTING = "hosting", "Servidores y dominios"
        CLOUD = "cloud", "Almacenamiento en la nube"
        TELECOM = "telecom", "Telefonía e internet"
        GYM = "gym", "Gimnasio y salud"
        MEDIA = "media", "Prensa y suscripciones"
        MEMBERSHIP = "membership", "Membresías y clubes"
        OTHER = "other", "Otro"

    service_kind = models.CharField("tipo", max_length=20, choices=Kind.choices,
                                    default=Kind.OTHER)
    provider = models.ForeignKey(
        "core.Party", verbose_name="a quién se lo pagas", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="subscriptions_sold",
    )
    plan = models.CharField("plan", max_length=120, blank=True)

    cycle = models.CharField("cada cuánto se cobra", max_length=20,
                             choices=Cycle.choices, default=Cycle.MONTHLY)
    amount = models.DecimalField("importe del cargo", max_digits=12, decimal_places=2,
                                 null=True, blank=True)
    charge_day = models.PositiveSmallIntegerField("día del cargo", null=True,
                                                  blank=True)
    paid_with = models.ForeignKey(
        "core.Account", verbose_name="con qué se paga", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="subscriptions",
    )

    access = models.CharField("de quién es la cuenta", max_length=20,
                              choices=Access.choices, default=Access.MINE)
    account_holder = models.ForeignKey(
        "core.Party", verbose_name="a nombre de quién está", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="subscriptions_held",
    )

    started_on = models.DateField("desde cuándo", null=True, blank=True)
    commitment_until = models.DateField("permanencia hasta", null=True, blank=True)
    cancel_url = models.URLField("cómo se cancela", max_length=400, blank=True)

    # Para detectar subidas sin guardar un historial entero.
    previous_amount = models.DecimalField("importe anterior", max_digits=12,
                                          decimal_places=2, null=True, blank=True)
    price_changed_on = models.DateField("cambió de precio el", null=True, blank=True)

    class Meta:
        verbose_name = "suscripción"
        verbose_name_plural = "suscripciones"

    def __str__(self):
        return f"{self.name} · {self.plan}" if self.plan else self.name

    @property
    def counts_as_asset(self) -> bool:
        return False        # un contrato no es un bien

    @property
    def yearly_cost(self):
        """El número que nadie tiene a mano.

        Doce cargos de 199 se leen como «199». Juntos son 2.388, y al lado de
        los otros siete servicios, otra cosa.
        """
        if not self.amount:
            return None
        return self.amount * CICLOS_AL_ANO.get(self.cycle, 12)

    @property
    def monthly_cost(self):
        anual = self.yearly_cost
        return anual / Decimal(12) if anual is not None else None

    @property
    def is_mine_to_cancel(self) -> bool:
        """Si no es tuya, el sistema no puede sugerirte cancelarla sin más."""
        return self.access != self.Access.THEIRS

    @property
    def price_rise(self):
        if self.previous_amount and self.amount and self.amount > self.previous_amount:
            return self.amount - self.previous_amount
        return None

    def context_line(self) -> str:
        partes = [
            self.get_service_kind_display(),
            str(self.provider) if self.provider else "",
            self.get_cycle_display().lower(),
        ]
        if self.access != self.Access.MINE and self.account_holder:
            partes.append(f"a nombre de {self.account_holder}")
        return ", ".join(p for p in partes if p)
