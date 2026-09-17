"""Regla: preferir couriers en la misma zona de recogida del pedido.

Esta es un filtro DURO: solo se mantienen los couriers de la misma zona.
Los couriers de otras zonas son fallback SOLO cuando no hay same-zone.
Esto coincide con el enunciado: "Candidatos en centro: cour_A y cour_C".
"""

from __future__ import annotations

from ..models import Courier, Order, Reason
from ..state import State
from .base import AssignmentRule, RuleResult


class SameZoneRule(AssignmentRule):
    """Preferir couriers cuyo zone coincide con order.pickup_zone.

    Filtro duro: descarta couriers de otras zonas si hay same-zone disponibles.
    Si no hay same-zone, pasa todos los candidatos (fallback).
    """

    @property
    def name(self) -> str:
        return "same_zone_preferred"

    def apply(
        self, order: Order, candidates: list[Courier], state: State
    ) -> RuleResult:
        """Filtra candidatos manteniendo solo los de la misma zona (si hay)."""
        if not candidates:
            return RuleResult(candidates=[])

        # Separar couriers por zona.
        same_zone = [c for c in candidates if c.zone == order.pickup_zone]
        other_zone = [c for c in candidates if c.zone != order.pickup_zone]

        if same_zone:
            # Filtro duro: mantener solo same-zone. Otros son fallback.
            detail = f"{same_zone[0].courier_id} is in pickup_zone={order.pickup_zone}"
            return RuleResult(
                candidates=same_zone,
                reason=Reason(rule=self.name, detail=detail),
            )
        else:
            # Fallback: no hay same-zone, usar lo que haya disponible.
            detail = f"no couriers in pickup_zone={order.pickup_zone}, using other zones"
            return RuleResult(
                candidates=candidates,
                reason=Reason(rule=self.name, detail=detail),
            )
