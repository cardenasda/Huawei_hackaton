"""Regla: respetar capacidad del courier — descartar couriers al tope.

Filtro DURO: los couriers con active_orders >= max_capacity se eliminan.
El reason detalla cuáles se saltaron y por qué.
"""

from __future__ import annotations

from ..models import Courier, Order, Reason
from ..state import State
from .base import AssignmentRule, RuleResult


class CapacityRule(AssignmentRule):
    """Filtra couriers que están a o sobre su max_capacity.

    Esta regla NUNCA permite asignar a un courier lleno. Si todos están
    llenos, retorna lista vacía → el engine encola o rechaza el pedido.
    """

    @property
    def name(self) -> str:
        return "capacity_ok"

    def apply(
        self, order: Order, candidates: list[Courier], state: State
    ) -> RuleResult:
        """Descarta couriers sin capacidad disponible."""
        if not candidates:
            return RuleResult(candidates=[])

        # Separar disponibles de llenos.
        available = [c for c in candidates if c.is_available]
        skipped = [c for c in candidates if not c.is_available]

        if not available:
            # Todos llenos: 0 couriers con capacidad.
            detail = f"0 couriers with free capacity (all full: {[c.courier_id for c in skipped]})"
            return RuleResult(candidates=[], reason=Reason(rule=self.name, detail=detail))

        # Construir detalle: mostrar el primer disponible y los saltados.
        first = available[0]
        if skipped:
            skipped_str = ", ".join(
                f"{c.courier_id} skipped: {c.active_orders}/{c.max_capacity} full"
                for c in skipped
            )
            detail = f"{first.courier_id} at {first.active_orders}/{first.max_capacity} ({skipped_str})"
        else:
            detail = f"{first.courier_id} at {first.active_orders}/{first.max_capacity}"

        return RuleResult(candidates=available, reason=Reason(rule=self.name, detail=detail))
