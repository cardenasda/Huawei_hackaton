"""Port del servicio de pricing — abstrae el API externo de tarifa dinámica.

Producción usa MockPricing (simula 30% de fallos/timeout).
Tests usan un fake para controlar el comportamiento de forma determinista.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from domain.models import Order


class PricingService(ABC):
    """Interfaz para el servicio de tarifa dinámica.

    El circuit breaker envuelve las llamadas a este servicio para
    manejar fallos de forma resiliente.
    """

    @abstractmethod
    def get_price(self, order: Order, now: datetime) -> float:
        """Retorna el precio dinámico en COP para este pedido.

        Args:
            order: El pedido a cotizar.
            now: Tiempo actual.

        Returns:
            Precio en COP.

        Raises:
            Exception: Si el servicio falla o hace timeout (el circuit breaker lo maneja).
        """
        ...
