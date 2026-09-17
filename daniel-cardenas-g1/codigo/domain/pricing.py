"""Circuit breaker + pricing — Fase 3.

Circuit Breaker (patrón de resiliencia):
- CLOSED: funcionamiento normal, las llamadas pasan. Se rastrean fallos consecutivos.
- OPEN: tras `failure_threshold` fallos consecutivos, bloquea llamadas por
  `recovery_timeout` segundos. Usa fallback (tarifa base fija).
- HALF_OPEN: tras recovery_timeout, permite UNA llamada de prueba.
  - Éxito → CLOSED (reset).
  - Fallo → OPEN (reset timer).

Esto garantiza que el servicio de tarifa dinámica (que falla ~30%) nunca
degrade toda la asignación: cuando el circuito está abierto, se usa tarifa fija.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from .models import PricingStatus


class _CircuitState(str, Enum):
    """Estados internos del circuit breaker (no se exponen fuera de este módulo)."""
    CLOSED = "closed"      # Funcionamiento normal.
    OPEN = "open"          # Bloqueado, esperando recovery_timeout.
    HALF_OPEN = "half_open"  # Permitiendo una llamada de prueba.


@dataclass
class PricingConfig:
    """Configuración de pricing + circuit breaker.

    Atributos:
        base_rate_cop: Tarifa base fija en COP (fallback cuando circuito abierto).
        per_km_rate_cop: Cargo por kilómetro en COP.
        failure_threshold: Fallos consecutivos para abrir el circuito.
        recovery_timeout_seconds: Tiempo antes de permitir una llamada de prueba.
    """
    base_rate_cop: float = 5000.0       # Tarifa fija de fallback (COP).
    per_km_rate_cop: float = 500.0      # Cargo por km (COP).
    failure_threshold: int = 3          # Fallos consecutivos para abrir.
    recovery_timeout_seconds: float = 15.0  # Tiempo antes de half-open.


class CircuitBreaker:
    """Circuit breaker thread-safe para el servicio de pricing.

    Uso:
        cb = CircuitBreaker(config)
        if cb.allow_call(now):
            try:
                price = pricing_service.get_price(...)
                cb.record_success()
            except Exception:
                cb.record_failure(now)
        else:
            price = config.base_rate_cop  # fallback
    """

    def __init__(self, config: PricingConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._state = _CircuitState.CLOSED  # Estado inicial: cerrado.
        self._failure_count = 0             # Contador de fallos consecutivos.
        self._opened_at: Optional[datetime] = None  # Momento en que se abrió.

    @property
    def state(self) -> _CircuitState:
        """Retorna el estado actual del circuit breaker."""
        with self._lock:
            return self._state

    def allow_call(self, now: datetime) -> bool:
        """Verifica si se permite una llamada al servicio de pricing.

        Si está OPEN y ha pasado recovery_timeout, transita a HALF_OPEN
        y permite una llamada de prueba.

        Args:
            now: Tiempo actual (inyectado para testabilidad).

        Returns:
            True si se permite la llamada, False si no.
        """
        with self._lock:
            if self._state == _CircuitState.CLOSED:
                return True  # Circuito cerrado: llamadas normales.
            if self._state == _CircuitState.OPEN:
                # Verificar si ha pasado el recovery_timeout.
                if self._opened_at and now >= self._opened_at + timedelta(
                    seconds=self._config.recovery_timeout_seconds
                ):
                    # Transitar a HALF_OPEN: permitir una llamada de prueba.
                    self._state = _CircuitState.HALF_OPEN
                    return True
                return False  # Circuito abierto: bloquear.
            # HALF_OPEN: ya se permitió una llamada de prueba, bloquear adicionales.
            return False

    def record_success(self) -> None:
        """Registra una llamada exitosa → cierra el circuito y resetea el contador."""
        with self._lock:
            self._state = _CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None

    def record_failure(self, now: datetime) -> None:
        """Registra una llamada fallida. Puede abrir el circuito.

        Si está HALF_OPEN y falla → vuelve a OPEN.
        Si los fallos consecutivos >= threshold → abre el circuito.

        Args:
            now: Tiempo actual (para registrar cuándo se abrió).
        """
        with self._lock:
            self._failure_count += 1
            if self._state == _CircuitState.HALF_OPEN:
                # La llamada de prueba falló → volver a OPEN.
                self._state = _CircuitState.OPEN
                self._opened_at = now
            elif self._failure_count >= self._config.failure_threshold:
                # Fallos consecutivos alcanzaron el threshold → abrir.
                self._state = _CircuitState.OPEN
                self._opened_at = now

    def get_status(self) -> PricingStatus:
        """Retorna el estado público del circuit breaker para la decisión.

        Mapea el estado interno al enum público de PricingStatus.
        """
        with self._lock:
            if self._state == _CircuitState.CLOSED:
                return PricingStatus.OK
            if self._state == _CircuitState.HALF_OPEN:
                return PricingStatus.CIRCUIT_HALF_OPEN
            return PricingStatus.CIRCUIT_OPEN_DEGRADED_FLAT_RATE

    def reset(self) -> None:
        """Force reset a CLOSED (para testing)."""
        with self._lock:
            self._state = _CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None


def compute_cost(
    distance_km: float,
    config: PricingConfig,
    pricing_status: PricingStatus,
    dynamic_price: Optional[float] = None,
) -> float:
    """Computa el costo del envío en COP.

    Si el circuito está abierto (degradado), usa la tarifa base fija.
    Si hay precio dinámico disponible, lo usa.
    Si no, usa base + per_km * distance.

    Args:
        distance_km: Distancia del envío en km.
        config: Configuración de pricing.
        pricing_status: Estado del circuit breaker.
        dynamic_price: Precio dinámico del servicio (opcional).

    Returns:
        Costo en COP.
    """
    if pricing_status == PricingStatus.CIRCUIT_OPEN_DEGRADED_FLAT_RATE:
        # Circuito abierto: usar tarifa fija de fallback.
        return config.base_rate_cop
    if dynamic_price is not None:
        # Precio dinámico disponible: usarlo.
        return dynamic_price
    # Fallback: tarifa base + cargo por km.
    return config.base_rate_cop + config.per_km_rate_cop * distance_km
