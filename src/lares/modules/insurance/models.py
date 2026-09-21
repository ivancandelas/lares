"""Seguros.

Una poliza no "pertenece" a un coche: lo asegura, y esa arista tiene vigencia
propia. Por eso la relacion vive en el grafo y no en una clave foranea: permite
responder que poliza estaba vigente el dia del siniestro, que cubria la
anterior, y asegurar varias cosas con una sola poliza.
"""

from django.db import models

from lares.core.models import Resource


class Policy(Resource):
    resource_kind = "policy"

    # Una póliza no se presta ni se pierde: se vence o se cancela.
    can_be_lent = False
    can_be_checked = False

    class Branch(models.TextChoices):
        VEHICLE = "vehicle", "Automóvil"
        HOME = "home", "Hogar"
        LIFE = "life", "Vida"
        HEALTH = "health", "Gastos médicos"
        LIABILITY = "liability", "Responsabilidad civil"
        VALUABLES = "valuables", "Objetos de valor"
        OTHER = "other", "Otro"

    class Cycle(models.TextChoices):
        YEARLY = "yearly", "Anual"
        SEMIANNUAL = "semiannual", "Semestral"
        QUARTERLY = "quarterly", "Trimestral"
        MONTHLY = "monthly", "Mensual"

    branch = models.CharField("ramo", max_length=20, choices=Branch.choices,
                              default=Branch.OTHER)
    policy_number = models.CharField("número de póliza", max_length=60, blank=True,
                                     db_index=True)
    insurer = models.ForeignKey(
        "core.Party", verbose_name="aseguradora", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="policies_issued",
    )
    agent = models.ForeignKey(
        "core.Party", verbose_name="agente", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="policies_brokered",
    )

    coverage_amount = models.DecimalField("suma asegurada", max_digits=16,
                                          decimal_places=2, null=True, blank=True)
    deductible = models.DecimalField("deducible", max_digits=16, decimal_places=2,
                                     null=True, blank=True)
    premium = models.DecimalField("prima", max_digits=16, decimal_places=2,
                                  null=True, blank=True)
    premium_cycle = models.CharField("cómo se paga", max_length=20,
                                     choices=Cycle.choices, default=Cycle.YEARLY)
    premium_day = models.PositiveSmallIntegerField("día de pago", null=True, blank=True)

    starts_on = models.DateField("vigente desde", null=True, blank=True)
    ends_on = models.DateField("vence el", null=True, blank=True, db_index=True)
    beneficiaries = models.CharField("beneficiarios", max_length=300, blank=True)

    class Meta:
        verbose_name = "póliza"
        verbose_name_plural = "pólizas"

    def __str__(self):
        if self.policy_number:
            return f"{self.name} · {self.policy_number}"
        return self.name

    @property
    def counts_as_asset(self) -> bool:
        return False        # una póliza es una cobertura, no un bien

    def context_line(self) -> str:
        partes = [
            self.get_branch_display(),
            str(self.insurer) if self.insurer else "",
            f"vence {self.ends_on:%d/%m/%Y}" if self.ends_on else "",
        ]
        return ", ".join(p for p in partes if p)

    def insured_resources(self):
        """Lo que cubre esta póliza, según el grafo."""
        from django.contrib.contenttypes.models import ContentType

        from lares.core.models import Link
        from lares.core.models.resource import Resource as _Resource

        ids = Link.objects.filter(
            role="insures",
            source_type=ContentType.objects.get_for_model(Policy),
            source_id=self.pk,
        ).values_list("target_id", flat=True)
        return _Resource.objects.filter(pk__in=ids)
