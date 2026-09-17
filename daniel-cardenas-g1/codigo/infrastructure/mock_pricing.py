"""Mock del servicio de pricing — simula un API externo de tarifa dinámica.

Tiene ~30% de probabilidad de fallo o timeout (>2s) para demostrar
el circuit breaker. Cuando funciona, retorna un precio dinámico basado
en distancia + factor de surge por hora del día.
"""

from __future__ import annotations

import random
import time
from datetime import datetime

from application.ports.pricing import PricingService
from domain.models import Order


class MockPricing(PricingService):
    """Simula un servicio de pricing con ~30% de tasa de fallo.

    Cuando funciona, calcula: (base + per_km * distance) * surge_multiplier
    donde surge_multiplier es 1.3 durante horas pico (almuerzo/cena).

    Atributos:
        _failure_rate: Probabilidad de fallo (0.0 a 1.0).
        _base_rate: Tarifa base en COP.
        _per_km_rate: Cargo por km en COP.
        _rng: Generador aleatorio (con seed para tests deterministas).
    """

    def __init__(
        self,
        failure_rate: float = 0.3,
        base_rate: float = 5000.0,
        per_km_rate: float = 500.0,
        seed: int | None = None,
    ) -> None:
        """Inicializa el mock con la tasa de fallo y seed opcionales.

        Args:
            failure_rate: Probabilidad de fallo (default 0.3 = 30%).
            base_rate: Tarifa base en COP.
            per_km_rate: Cargo por km en COP.
            seed: Seed para el generador aleatorio (None = aleatorio real).
        """
        self._failure_rate = failure_rate
        self._base_rate = base_rate
        self._per_km_rate = per_km_rate
        self._rng = random.Random(seed)

    def get_price(self, order: Order, now: datetime) -> float:
        """Retorna el precio dinámico, o lanza Exception ~30% de las veces.

        Args:
            order: El pedido a cotizar.
            now: Tiempo actual (para calcular surge por hora).

        Returns:
            Precio dinámico en COP (redondeado).

        Raises:
            ConnectionError: Si el servicio "falla" (simulado).
        """
        # Simular fallo o timeout.
        if self._rng.random() < self._failure_rate:
            # Simular respuesta lenta y luego fallo.
            time.sleep(0.01)  # En producción real sería >2s.
            raise ConnectionError("pricing service timeout")

        # Precio dinámico: base + per_km * distance + surge por hora.
        hour = now.hour
        # Surge durante almuerzo (12-14) y cena (19-21).
        surge_multiplier = 1.3 if hour in (12, 13, 19, 20) else 1.0
        price = (self._base_rate + self._per_km_rate * order.distance_km) * surge_multiplier
        return round(price)
