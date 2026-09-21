"""Inmuebles.

El modelo es una cartera, no una vivienda. Una persona puede tener dos casas, un
terreno, un departamento y un local, cada uno con su escritura, su predial, sus
servicios y su propio historial. Y puede, ademas, vivir en uno que no es suyo.

Tenencia y uso son ejes distintos, y confundirlos obliga a rehacer el modulo:

    tenencia  que relacion tienes con el   (propio, rentado, prestado...)
    uso       que se hace con el           (habitado, vacio, en renta...)

Un inmueble puede ser rentado + habitado (donde vives y pagas renta) o propio +
en renta (el que rentas a alguien). Son situaciones opuestas: en una pagas y en
la otra cobras.
"""

from django.db import models

from lares.core.models import Resource


class Property(Resource):
    resource_kind = "property"

    # Una casa no se extravía, y dejársela a alguien es un arrendamiento:
    # tiene su propio módulo, con contrato, renta y depósito.
    can_be_lent = False
    can_be_checked = False

    class Type(models.TextChoices):
        HOUSE = "house", "Casa"
        APARTMENT = "apartment", "Departamento"
        LAND = "land", "Terreno"
        COMMERCIAL = "commercial", "Local comercial"
        WAREHOUSE = "warehouse", "Bodega"
        PARKING = "parking", "Estacionamiento"
        OTHER = "other", "Otro"

    class Tenure(models.TextChoices):
        OWNED = "owned", "Propio"
        CO_OWNED = "co_owned", "En copropiedad"
        RENTED = "rented", "Rentado (soy el inquilino)"
        BORROWED = "borrowed", "Prestado"
        USUFRUCT = "usufruct", "En usufructo"
        MANAGED = "managed", "Administrado para un tercero"

    class Use(models.TextChoices):
        LIVED_IN = "lived_in", "Lo habito"
        EMPTY = "empty", "Vacío"
        RENTED_OUT = "rented_out", "Se lo rento a un inquilino"
        FOR_SALE = "for_sale", "En venta"
        LENT = "lent", "Prestado a alguien"
        OTHER = "other", "Otro"

    property_type = models.CharField("tipo", max_length=20, choices=Type.choices,
                                     default=Type.HOUSE)
    tenure = models.CharField("régimen de tenencia", max_length=20,
                              choices=Tenure.choices, default=Tenure.OWNED)
    use = models.CharField("uso", max_length=20, choices=Use.choices,
                           default=Use.LIVED_IN)

    address = models.CharField("dirección", max_length=250, blank=True)
    city = models.CharField("ciudad", max_length=120, blank=True)
    subdivision = models.CharField("estado", max_length=10, blank=True)

    land_m2 = models.DecimalField("superficie del terreno (m²)", max_digits=12,
                                  decimal_places=2, null=True, blank=True)
    built_m2 = models.DecimalField("construcción (m²)", max_digits=12,
                                   decimal_places=2, null=True, blank=True)

    # Datos que solo tienen sentido si es tuyo.
    cadastral_id = models.CharField("clave catastral", max_length=60, blank=True)
    deed_number = models.CharField("escritura", max_length=60, blank=True)
    deed_date = models.DateField("fecha de escritura", null=True, blank=True)
    ownership_share = models.DecimalField("tu parte (%)", max_digits=5, decimal_places=2,
                                          null=True, blank=True)
    predial_month = models.PositiveSmallIntegerField(
        "mes del predial", null=True, blank=True, default=1
    )
    predial_amount = models.DecimalField("predial estimado", max_digits=12,
                                         decimal_places=2, null=True, blank=True)

    # La renta, el deposito y el fin de contrato viven en el modulo de
    # arrendamiento, no aqui: son del contrato, no del inmueble, y funcionan
    # igual seas el inquilino o el arrendador.

    class Meta:
        verbose_name = "inmueble"
        verbose_name_plural = "inmuebles"

    def __str__(self):
        return self.name

    @property
    def is_mine(self) -> bool:
        return self.tenure in (self.Tenure.OWNED, self.Tenure.CO_OWNED,
                               self.Tenure.USUFRUCT)

    @property
    def counts_as_asset(self) -> bool:
        """La casa donde vives de renta no es un bien tuyo.

        Genera gasto, obligaciones y documentos, pero sumarla al patrimonio
        seria contar como propio algo que devuelves al terminar el contrato.
        """
        return super().counts_as_asset and self.is_mine

    def context_line(self) -> str:
        partes = [
            self.get_property_type_display(),
            self.get_tenure_display() if not self.is_mine else "",
            self.city,
            f"{self.built_m2:,.0f} m² construidos" if self.built_m2 else "",
        ]
        return ", ".join(p for p in partes if p)


class Service(Resource):
    """Agua, luz, gas, internet: contratos con ciclo de pago propio.

    Es un Resource y no una tabla suelta porque tiene proveedor, documentos
    (los recibos), coste y ciclo de vida: se contrata y se da de baja.
    """

    resource_kind = "service"

    # «Prestar la luz» no significa nada.
    can_be_lent = False
    can_be_checked = False

    class Kind(models.TextChoices):
        WATER = "water", "Agua"
        POWER = "power", "Electricidad"
        GAS = "gas", "Gas"
        INTERNET = "internet", "Internet"
        PHONE = "phone", "Teléfono"
        WASTE = "waste", "Recolección"
        HOA = "hoa", "Cuota de condominio"
        SECURITY = "security", "Seguridad"
        OTHER = "other", "Otro"

    class Cycle(models.TextChoices):
        MONTHLY = "monthly", "Cada mes"
        BIMONTHLY = "bimonthly", "Cada dos meses"
        QUARTERLY = "quarterly", "Cada tres meses"
        YEARLY = "yearly", "Cada año"

    service_kind = models.CharField("servicio", max_length=20, choices=Kind.choices,
                                    default=Kind.OTHER)
    property_ref = models.ForeignKey(
        Property, verbose_name="del inmueble", on_delete=models.CASCADE,
        related_name="services",
    )
    provider = models.ForeignKey(
        "core.Party", verbose_name="proveedor", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="services_provided",
    )
    contract_number = models.CharField("número de contrato", max_length=60, blank=True)
    cycle = models.CharField("periodicidad", max_length=20, choices=Cycle.choices,
                             default=Cycle.MONTHLY)
    due_day = models.PositiveSmallIntegerField("día de pago", null=True, blank=True)
    typical_amount = models.DecimalField("importe habitual", max_digits=12,
                                         decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "servicio"
        verbose_name_plural = "servicios"

    def __str__(self):
        return f"{self.get_service_kind_display()} · {self.property_ref.name}"

    @property
    def counts_as_asset(self) -> bool:
        return False        # un contrato de luz no es patrimonio

    def context_line(self) -> str:
        partes = [
            str(self.provider) if self.provider else "",
            self.contract_number,
            self.get_cycle_display().lower(),
        ]
        return ", ".join(p for p in partes if p)
