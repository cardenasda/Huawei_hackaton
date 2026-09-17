"""Estado compartido thread-safe para el motor FlowMatch.

Decisiones de diseño:
- Todo el estado mutable (carga de couriers, cola, historial) vive aquí.
- Locks granulares: un RLock por courier para active_orders, locks dedicados
  para cola e historial. Esto permite concurrencia sin bloqueo global.
- RLock permite llamadas anidadas desde el mismo hilo.
- Operaciones atómicas: assign_to_courier valida capacidad E incrementa en un lock.
  Esto garantiza que dos hilos no puedan sobre-asignar el mismo cupo (Bono B).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import Courier, Order


@dataclass
class QueuedOrder:
    """Pedido en espera en la cola.

    Atributos:
        order: El pedido original.
        queued_at: Momento en que entró a la cola (para métricas/timeout).
    """
    order: Order
    queued_at: datetime


class State:
    """Estado compartido thread-safe.

    Garantías:
    - assign_to_courier es atómica: valida capacidad + incrementa bajo lock.
    - Dos hilos no pueden sobre-asignar el mismo cupo de un courier.
    - Las operaciones de cola son atómicas.
    - El historial de surge/assignments se purga automáticamente (sliding window).
    """

    def __init__(self, couriers: list[Courier]) -> None:
        # Diccionario de couriers para lookup O(1). Los couriers son mutables.
        self._couriers: dict[str, Courier] = {c.courier_id: c for c in couriers}
        # Lock por courier para concurrencia de granularidad fina en active_orders.
        self._courier_locks: dict[str, threading.RLock] = {
            c.courier_id: threading.RLock() for c in couriers
        }
        # Cola de pedidos en espera (FIFO).
        self._queue: deque[QueuedOrder] = deque()
        self._queue_lock = threading.RLock()
        # Historial de surge: lista de (timestamp, zone) para sliding window.
        self._surge_history: list[tuple[datetime, str]] = []
        self._surge_lock = threading.RLock()
        # Historial de asignaciones: (timestamp, courier_id) para rate limiting.
        self._assignment_history: list[tuple[datetime, str]] = []
        self._assignment_lock = threading.RLock()

    # ---- Estado de couriers ----

    def get_couriers(self) -> list[Courier]:
        """Retorna el estado actual de todos los couriers (snapshot)."""
        return list(self._couriers.values())

    def get_courier(self, courier_id: str) -> Optional[Courier]:
        """Retorna un courier por ID, o None si no existe."""
        return self._couriers.get(courier_id)

    def assign_to_courier(self, courier_id: str) -> bool:
        """Asigna atómicamente un nuevo pedido a un courier.

        Returns:
            True si se asignó, False si el courier está a capacidad máxima o no existe.

        Esta es la ÚNICA forma de incrementar active_orders → previene race conditions.
        La validación de capacidad y el incremento ocurren bajo el mismo lock,
        por lo que es imposible que dos hilos asignen al mismo cupo.
        """
        lock = self._courier_locks.get(courier_id)
        if lock is None:
            return False  # Courier no existe.
        with lock:
            courier = self._couriers[courier_id]
            if not courier.is_available:
                return False  # Courier lleno.
            courier.active_orders += 1  # Incremento atómico bajo lock.
            return True

    def release_courier(self, courier_id: str) -> None:
        """Libera un pedido de un courier (para testing/cancelación).

        Decrementa active_orders si es > 0. Thread-safe.
        """
        with self._courier_locks[courier_id]:
            courier = self._couriers[courier_id]
            if courier.active_orders > 0:
                courier.active_orders -= 1

    # ---- Cola de espera ----

    def enqueue(self, order: Order, now: datetime) -> None:
        """Añade un pedido a la cola de espera. Thread-safe."""
        with self._queue_lock:
            self._queue.append(QueuedOrder(order=order, queued_at=now))

    def dequeue(self) -> Optional[QueuedOrder]:
        """Saca el siguiente pedido de la cola (FIFO). Thread-safe."""
        with self._queue_lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def queue_size(self) -> int:
        """Retorna el tamaño actual de la cola. Thread-safe."""
        with self._queue_lock:
            return len(self._queue)

    # ---- Historial de surge (sliding window) ----

    def record_surge_event(self, timestamp: datetime, zone: str) -> None:
        """Registra un evento de surge para análisis de sliding window."""
        with self._surge_lock:
            self._surge_history.append((timestamp, zone))

    def get_surge_events(
        self, window_seconds: float, now: datetime
    ) -> list[tuple[datetime, str]]:
        """Retorna eventos de surge dentro de la ventana deslizante.

        Purga los eventos viejos (fuera de la ventana) para mantener
        el tamaño del historial acotado. O(n) pero n es pequeño.
        """
        with self._surge_lock:
            cutoff = now.timestamp() - window_seconds
            # Purgar eventos fuera de la ventana.
            self._surge_history = [
                (ts, z) for ts, z in self._surge_history if ts.timestamp() >= cutoff
            ]
            return list(self._surge_history)

    # ---- Historial de asignaciones (rate limiting por courier) ----

    def record_assignment(self, timestamp: datetime, courier_id: str) -> None:
        """Registra cuándo se asignó un courier (para rate limiting)."""
        with self._assignment_lock:
            self._assignment_history.append((timestamp, courier_id))

    def get_courier_assignments(
        self, courier_id: str, window_seconds: float, now: datetime
    ) -> list[datetime]:
        """Retorna los timestamps de asignaciones de un courier en la ventana.

        Purga las asignaciones viejas (fuera de la ventana) para mantener
        el historial acotado. Esto implementa el sliding window real
        (no ventana fija).
        """
        with self._assignment_lock:
            cutoff = now.timestamp() - window_seconds
            # Purgar asignaciones fuera de la ventana.
            self._assignment_history = [
                (ts, cid) for ts, cid in self._assignment_history
                if ts.timestamp() >= cutoff
            ]
            # Filtrar solo las del courier solicitado.
            return [
                ts for ts, cid in self._assignment_history if cid == courier_id
            ]

    # ---- Snapshot para debugging / UI ----

    def snapshot(self) -> dict:
        """Retorna un snapshot serializable del estado actual (para UI/debug)."""
        return {
            "couriers": [
                {
                    "courier_id": c.courier_id,
                    "zone": c.zone,
                    "active_orders": c.active_orders,
                    "max_capacity": c.max_capacity,
                }
                for c in self._couriers.values()
            ],
            "queue_size": self.queue_size(),
        }
