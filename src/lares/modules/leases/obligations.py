"""Cobrar la renta, pagarla, y las fechas del contrato."""

import datetime as dt

from lares.core.registry import ObligationProvider, ObligationSpec

from .services import next_rent


class RentProvider(ObligationProvider):
    """El cobro y el pago, con urgencias distintas.

    No pagar la renta tiene consecuencias inmediatas. No cobrarla se nota
    despues, y por eso conviene que salte igual: un mes sin cobrar es un mes
    que ya no se recupera.
    """

    key = "leases.rent"
    label = "Renta"
    applies_to = "lease"

    def generate(self, lease, on_date: dt.date):
        if not lease.is_live:
            return []

        import calendar

        # Tres meses recorridos para quedarse con dos por venir: pasado el dia
        # de pago, el mes corriente ya no cuenta, y avisar de uno solo deja la
        # renta de fin de mes sin margen para moverse.
        specs = []
        cursor = on_date.replace(day=1)
        for _ in range(3):
            if len(specs) == 2:
                break
            dia = min(lease.rent_day,
                      calendar.monthrange(cursor.year, cursor.month)[1])
            vence = dt.date(cursor.year, cursor.month, dia)
            if vence >= on_date and not (lease.ends_on and vence > lease.ends_on):
                cobrar = lease.is_landlord
                specs.append(ObligationSpec(
                    dedupe_key=f"lease:{lease.pk}:rent:{vence:%Y-%m}",
                    title=(f"Cobrar la renta de {lease.property_ref.name}" if cobrar
                           else f"Pagar la renta de {lease.property_ref.name}"),
                    due_on=vence,
                    amount=lease.rent_amount,
                    currency=lease.currency or None,
                    counterparty=lease.counterpart,
                    severity="critical" if not cobrar else "high",
                    remind_offsets=(-5, -1) if not cobrar else (-3,),
                    payload={"direction": lease.direction},
                ))
            cursor = (cursor + dt.timedelta(days=32)).replace(day=1)
        return specs


class LeaseEndProvider(ObligationProvider):
    """Renovar o mudarse no se decide en una semana."""

    key = "leases.end"
    label = "Fin de contrato"
    applies_to = "lease"

    def generate(self, lease, on_date: dt.date):
        if not lease.ends_on or lease.ends_on < on_date:
            return []
        return [ObligationSpec(
            dedupe_key=f"lease:{lease.pk}:end:{lease.ends_on:%Y-%m-%d}",
            title=f"Acaba el contrato de {lease.property_ref.name}",
            due_on=lease.ends_on,
            currency=lease.currency or None,
            counterparty=lease.counterpart,
            severity="high",
            remind_offsets=(-90, -60, -30, -15),
            payload={"direction": lease.direction},
        )]


class IncreaseProvider(ObligationProvider):
    """El incremento pactado se pierde si nadie lo aplica a tiempo."""

    key = "leases.increase"
    label = "Incremento de renta"
    applies_to = "lease"

    def generate(self, lease, on_date: dt.date):
        cuando = lease.next_increase
        if not (lease.is_live and cuando):
            return []
        nueva = next_rent(lease)
        return [ObligationSpec(
            dedupe_key=f"lease:{lease.pk}:increase:{cuando:%Y-%m}",
            title=f"Toca el incremento de {lease.property_ref.name}",
            due_on=cuando,
            amount=nueva if nueva != lease.rent_amount else None,
            currency=lease.currency or None,
            counterparty=lease.counterpart,
            severity="normal",
            remind_offsets=(-30, -7),
            payload={"kind": lease.increase_kind},
        )]
