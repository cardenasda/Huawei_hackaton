"""Regla: preferir el courier que minimiza el costo del envío (Fase 3).

Modelo de costo: base_rate + per_km_rate * distance_km.
Como la distancia es por pedido (igual para todos los couriers), esta regla
principalmente ordena por factores de costo específicos del courier.
Por ahora es pass-through (la distancia es compartida), pero aquí se añadirían
factores como penalización por zona o costo de combustible.
"""

from __future__ import annotations

from ..models import Courier, Order, Reason
from ..state import State
from .base import AssignmentRule, RuleResult


class MinCostRule(AssignmentRule):
    """Ordena candidatos para minimizar el costo del envío.

    Con distancia compartida, el costo es igual entre couriers, así que
    esta regla es pass-through que documenta la intención de optimización.
    Factores de costo específicos por courier se añadirían aquí en el futuro.
    """

    @property
    def name(self) -> str:
        return "min_cost"

    def apply(
        self, order: Order, candidates: list[Courier], state: State
    ) -> RuleResult:
        """Mantiene el orden de candidatos (costo compartido) y documenta la intención."""
        if not candidates:
            return RuleResult(candidates=[])

        # Futuro: añadir factores de costo específicos por courier aquí.
        # Por ahora, los candidatos ya están ordenados por least_loaded.
        chosen = candidates[0]
        detail = f"{chosen.courier_id} minimizes cost (distance={order.distance_km}km shared)"
        return RuleResult(candidates=candidates, reason=Reason(rule=self.name, detail=detail))
