from django.db import models

from lares.core.models import Resource


class Belonging(Resource):
    """Objetos que merece la pena rastrear.

    El criterio no es el precio: es que cumpla alguna de estas condiciones.

      - tiene garantia vigente o factura que habria que encontrar
      - se puede vender
      - habria que reclamarlo a un seguro
      - duele perderlo, aunque valga poco

    Un refrigerador entra por la garantia y la factura; una bicicleta por la
    reventa y el robo; un anillo por el seguro; una guitarra por las cuatro.
    Una escoba y una cama no entran por ninguna. Un inventario exhaustivo del
    hogar es una tarea que nadie termina.
    """

    resource_kind = "belonging"

    class Category(models.TextChoices):
        APPLIANCE = "appliance", "Electrodoméstico"
        ELECTRONICS = "electronics", "Electrónica"
        TOOL = "tool", "Herramienta"
        SPORTS = "sports", "Deporte y bicicletas"
        INSTRUMENT = "instrument", "Instrumento musical"
        JEWELRY = "jewelry", "Joyería y relojes"
        ART = "art", "Arte y coleccionables"
        FURNITURE = "furniture", "Mobiliario"
        OTHER = "other", "Otro"

    category = models.CharField("categoría", max_length=20, choices=Category.choices,
                                default=Category.OTHER)
    brand = models.CharField("marca", max_length=80, blank=True)
    model_name = models.CharField("modelo", max_length=80, blank=True)
    serial_number = models.CharField("número de serie", max_length=80, blank=True,
                                     db_index=True)

    warranty_until = models.DateField("garantía hasta", null=True, blank=True)
    warranty_note = models.CharField("qué cubre la garantía", max_length=200, blank=True)

    # Piezas que conviene tener valuadas: joyas, instrumentos, arte.
    appraised_value = models.DecimalField("valor de avalúo", max_digits=16,
                                          decimal_places=2, null=True, blank=True)
    appraised_on = models.DateField("avalúo del", null=True, blank=True)

    class Meta:
        verbose_name = "objeto"
        verbose_name_plural = "objetos"

    def __str__(self):
        partes = [p for p in (self.brand, self.model_name) if p]
        return f"{self.name} ({' '.join(partes)})" if partes else self.name

    @property
    def is_valuable(self) -> bool:
        """Lo que conviene asegurar y revisar de vez en cuando."""
        if self.category in (self.Category.JEWELRY, self.Category.ART,
                             self.Category.INSTRUMENT):
            return True
        valor = self.appraised_value or self.current_value or self.purchase_amount or 0
        return valor >= 15000
