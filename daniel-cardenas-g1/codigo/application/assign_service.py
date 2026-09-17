"""Caso de uso: asignar un pedido a un courier.

Este es el entry point para los adapters de API/UI. Recibe un dict crudo
de pedido, lo valida, y delega al engine de dominio.
"""

from __future__ import annotations

from domain.engine import AssignmentEngine
from domain.models import Decision, Order


class AssignOrderUseCase:
    """Caso de uso: asignar un pedido a un courier.

    Adapter delgado entre presentation (API/UI) y domain engine.
    Su única responsabilidad es validar la entrada y delegar al engine.
    """

    def __init__(self, engine: AssignmentEngine) -> None:
        """Inicializa con el engine inyectado.

        Args:
            engine: El motor de asignación configurado.
        """
        self._engine = engine

    def execute(self, order_data: dict) -> dict:
        """Procesa un pedido desde un dict crudo de entrada.

        Args:
            order_data: Dict crudo del pedido (ej: payload JSON o formulario UI).
                Debe contener: order_id, timestamp, pickup_zone, distance_km, priority.

        Returns:
            Decision como dict (serializable para API/UI).
        """
        # Validar y construir el Order (fail-fast).
        order = Order.from_dict(order_data)
        # Delegar al engine.
        decision = self._engine.assign(order)
        return decision.to_dict()

    def execute_order(self, order: Order) -> Decision:
        """Procesa un objeto Order ya validado directamente.

        Usado por tests o llamadas internas que ya tienen un Order construido.

        Args:
            order: El pedido validado.

        Returns:
            Decision inmutable.
        """
        return self._engine.assign(order)
