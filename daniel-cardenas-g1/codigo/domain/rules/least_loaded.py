"""Regla: preferir el courier con menor active_orders (balanceo de carga).

Ordenamiento SUAVE: no descarta candidatos, solo los ordena por carga ascendente.
El primer elemento después de esta regla es el de menor carga.
"""

from __future__ import annotations

from ..models import Courier, Order, Reason
from ..state import State
from .base import AssignmentRule, RuleResult


class LeastLoadedRule(AssignmentRule):
    """Ordena candidatos por active_orders ascendente (menor carga primero).

    Esto distribuye el trabajo de forma pareja entre repartidores.
    """

    @property
    def name(self) -> str:
        return "least_loaded"

    def apply(
        self, order: Order, candidates: list[Courier], state: State
    ) -> RuleResult:
        """Ordena candidatos por menor active_orders."""
        if not candidates:
            return RuleResult(candidates=[])

        # Ordenar por carga ascendente (menos pedidos activos primero).
        ordered = sorted(candidates, key=lambda c: c.active_orders)
        chosen = ordered[0]
        detail = (
            f"{chosen.courier_id} chosen ({chosen.active_orders} active order, "
            f"lowest among valid)"
        )
        return RuleResult(candidates=ordered, reason=Reason(rule=self.name, detail=detail))
