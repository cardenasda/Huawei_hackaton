"""Controlador de surge — Fase 2: sliding window + contención.

Responsabilidades:
1. Rate limiting por courier (sliding window): un courier no puede recibir
   más de N pedidos nuevos en W segundos, aunque tenga capacidad libre.
2. Balanceo de zona: si una zona está saturada, usar couriers de zonas vecinas.
3. Modo de contención: si TODOS los couriers están llenos Y la cola crece
   por `containment_threshold` pedidos consecutivos, activar contención temporal
   que REJECTA pedidos normal por `containment_duration` segundos (auto-expirable).
   Los pedidos express siguen encolándose (QUEUED).

El flujo está separado en dos métodos:
- check_active_containment(): se llama ANTES de la pipeline (contención ya activa).
- record_full_event(): se llama DESPUÉS de la pipeline (puede activar contención).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .models import Order, Priority, Reason
from .state import State


@dataclass
class SurgeConfig:
    """Configuración del control de surge (todo ajustable).

    Atributos:
        courier_rate_max: Máximo de pedidos nuevos por courier en la ventana.
        courier_rate_window_seconds: Tamaño de la ventana deslizante en segundos.
        containment_threshold: Pedidos consecutivos "all full" para activar contención.
        containment_duration_seconds: Duración de la contención en segundos.
        neighbor_zones: Mapa de zonas vecinas para balanceo de zona.
    """
    courier_rate_max: int = 3
    courier_rate_window_seconds: float = 10.0
    containment_threshold: int = 3
    containment_duration_seconds: float = 120.0
    neighbor_zones: dict[str, list[str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Inicializa neighbor_zones como dict vacío si es None."""
        if self.neighbor_zones is None:
            self.neighbor_zones = {}


@dataclass
class SurgeDecision:
    """Resultado de la evaluación de surge para un pedido.

    Atributos:
        should_reject: True si el pedido debe ser REJECTED.
        should_queue: True si el pedido debe ser QUEUED.
        reason: Explicación de la decisión (para trazabilidad).
    """
    should_reject: bool = False
    should_queue: bool = False
    reason: Optional[Reason] = None


class SurgeController:
    """Gestiona rate limiting y modo de contención.

    Thread-safe: el flag de contención y el contador de consecutivos-full
    están protegidos por un lock.
    """

    def __init__(self, config: SurgeConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        # Estado de contención.
        self._containment_active: bool = False
        self._containment_expires_at: Optional[datetime] = None
        self._consecutive_full: int = 0  # Contador de pedidos consecutivos "all full".

    @property
    def is_containment_active(self) -> bool:
        """True si el modo de contención está activo."""
        return self._containment_active

    def check_active_containment(
        self, order: Order, now: datetime
    ) -> SurgeDecision:
        """Verifica si la contención YA está activa de un pedido anterior.

        Se llama ANTES de la pipeline. Si la contención está activa:
        - Pedidos normal → REJECTED inmediatamente con surge_window_active (sin pipeline).
        - Pedidos express → QUEUED con surge_window_active.
        - Si la contención expiró → se desactiva y retorna vacío (continúa normal).

        Args:
            order: El pedido entrante.
            now: Tiempo actual (inyectado para testabilidad).

        Returns:
            SurgeDecision indicando si se debe rechazar/encolar.
        """
        with self._lock:
            if not self._containment_active:
                return SurgeDecision()  # No hay contención, continuar normal.

            # Verificar auto-expiración.
            if self._containment_expires_at and now >= self._containment_expires_at:
                # La contención expiró → desactivar y resetear.
                self._containment_active = False
                self._containment_expires_at = None
                self._consecutive_full = 0
                return SurgeDecision()

            # La contención está activa y no ha expirado.
            if order.priority == Priority.NORMAL:
                # Pedidos normal → REJECTED inmediatamente (sin recorrer repartidores).
                return SurgeDecision(
                    should_reject=True,
                    reason=Reason(
                        rule="surge_window_active",
                        detail=f"containment active until {self._containment_expires_at.isoformat()}",
                    ),
                )
            else:
                # Pedidos express → QUEUED (no se rechazan).
                return SurgeDecision(
                    should_queue=True,
                    reason=Reason(
                        rule="surge_window_active",
                        detail=f"containment active, express order queued",
                    ),
                )

    def record_full_event(
        self, order: Order, now: datetime
    ) -> SurgeDecision:
        """Registra que un pedido encontró todos los couriers llenos (sin candidatos).

        Se llama DESPUÉS de la pipeline cuando no quedan candidatos.
        Rastrea eventos "all full" consecutivos y puede activar contención.

        Args:
            order: El pedido que no encontró courier disponible.
            now: Tiempo actual.

        Returns:
            SurgeDecision indicando si el pedido debe ser rechazado (contención
            recién activada) o encolado.
        """
        with self._lock:
            self._consecutive_full += 1
            if self._consecutive_full >= self._config.containment_threshold:
                # Activar contención: se alcanzó el threshold de consecutivos full.
                self._containment_active = True
                self._containment_expires_at = now + timedelta(
                    seconds=self._config.containment_duration_seconds
                )
                if order.priority == Priority.NORMAL:
                    # Pedido normal → REJECTED con surge_protection_active.
                    return SurgeDecision(
                        should_reject=True,
                        reason=Reason(
                            rule="surge_protection_active",
                            detail=(
                                f"all couriers full, queue growing for "
                                f"{self._consecutive_full} orders "
                                f"(window={int(self._config.containment_duration_seconds)}s)"
                            ),
                        ),
                    )
                else:
                    # Pedido express → QUEUED incluso con contención activa.
                    return SurgeDecision(
                        should_queue=True,
                        reason=Reason(
                            rule="surge_protection_active",
                            detail=(
                                f"all couriers full, queue growing for "
                                f"{self._consecutive_full} orders; express order queued"
                            ),
                        ),
                    )
            # Aún no se alcanza el threshold → solo encolar.
            return SurgeDecision()

    def reset_full_counter(self) -> None:
        """Resetea el contador de consecutivos-full.

        Se llama cuando se asigna un pedido exitosamente (hay couriers disponibles).
        """
        with self._lock:
            self._consecutive_full = 0

    def is_courier_rate_limited(
        self, courier_id: str, state: State, now: datetime
    ) -> bool:
        """Verifica si un courier excedió su rate limit (sliding window).

        Cuenta las asignaciones del courier en la ventana deslizante.
        Si >= courier_rate_max, el courier está rate-limited.

        Args:
            courier_id: ID del courier a verificar.
            state: Estado compartido (historial de asignaciones).
            now: Tiempo actual.

        Returns:
            True si el courier está rate-limited (no puede recibir más pedidos ahora).
        """
        assignments = state.get_courier_assignments(
            courier_id,
            self._config.courier_rate_window_seconds,
            now,
        )
        return len(assignments) >= self._config.courier_rate_max

    def get_neighbor_zones(self, zone: str) -> list[str]:
        """Retorna las zonas vecinas de una zona para balanceo.

        Args:
            zone: Zona de origen.

        Returns:
            Lista de zonas vecinas (vacía si no hay configuradas).
        """
        return self._config.neighbor_zones.get(zone, [])
