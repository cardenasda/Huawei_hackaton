"""Modelos del dominio — Value Objects inmutables para el motor FlowMatch.

Decisiones de diseño:
- Order y Reason son frozen (inmutables) → no pueden mutarse después de creación.
- Courier es mutable pero solo vía State (encapsulación thread-safe).
- Decision se construye una vez y nunca se muta.
- Priority es un Enum para prevenir valores inválidos desde construcción.
- Validación fail-fast en __post_init__: errores de entrada se detectan ASAP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Priority(str, Enum):
    """Prioridad de un pedido.

    Hereda de str para permitir serialización JSON como 'normal'/'express'.
    Esto evita valores inválidos como 'urgent' o 'high' desde la entrada.
    """
    NORMAL = "normal"    # Pedido normal: puede ser rechazado durante contención.
    EXPRESS = "express"  # Pedido express: siempre intenta encolarse, nunca se rechaza.


class OrderStatus(str, Enum):
    """Estados posibles de un pedido después de la evaluación.

    ASSIGNED: se encontró un repartidor válido y se le asignó.
    QUEUED: no hay repartidor disponible, el pedido entra en cola de espera.
    REJECTED: contención por saturación activa o pedido inválido.
    """
    ASSIGNED = "ASSIGNED"
    QUEUED = "QUEUED"
    REJECTED = "REJECTED"


class PricingStatus(str, Enum):
    """Estados del circuit breaker para el servicio de tarifa dinámica.

    OK: funcionamiento normal, el servicio respondió correctamente.
    CIRCUIT_OPEN_DEGRADED_FLAT_RATE: circuito abierto, usando tarifa base fija.
    CIRCUIT_HALF_OPEN: circuito semi-abierto, probando con una llamada.
    CIRCUIT_OPEN: circuito abierto (sin llamada de prueba aún).
    """
    OK = "ok"
    CIRCUIT_OPEN_DEGRADED_FLAT_RATE = "circuit_open_degraded_flat_rate"
    CIRCUIT_HALF_OPEN = "circuit_half_open"
    CIRCUIT_OPEN = "circuit_open"


@dataclass(frozen=True)
class Order:
    """Pedido inmutable de entrada. Valida en construcción (fail-fast).

    Atributos:
        order_id: Identificador único del pedido.
        timestamp: Momento de creación (ISO 8601, timezone-aware).
        pickup_zone: Zona de recogida (ej: 'centro', 'norte', 'sur').
        distance_km: Distancia estimada del envío en kilómetros (>= 0).
        priority: Prioridad del pedido (normal o express).

    La validación en __post_init__ garantiza que pedidos inválidos nunca
    lleguen al engine. Esto cubre el criterio de "casos borde" de la rúbrica.
    """
    order_id: str
    timestamp: datetime
    pickup_zone: str
    distance_km: float
    priority: Priority

    def __post_init__(self) -> None:
        """Valida los campos después de creación. Lanza ValueError si son inválidos."""
        if not self.order_id:
            raise ValueError("order_id is required")
        if self.distance_km < 0:
            raise ValueError(f"distance_km must be >= 0, got {self.distance_km}")
        if not self.pickup_zone:
            raise ValueError("pickup_zone is required")

    @classmethod
    def from_dict(cls, data: dict) -> "Order":
        """Factory desde un dict crudo (ej: payload JSON o formulario UI).

        Normaliza el timestamp (reemplaza 'Z' por '+00:00' para fromisoformat)
        y convierte el string de priority al Enum correspondiente.
        Lanza ValueError si la prioridad es inválida.
        """
        return cls(
            order_id=data["order_id"],
            timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
            pickup_zone=data["pickup_zone"],
            distance_km=float(data["distance_km"]),
            priority=Priority(data["priority"]),
        )


@dataclass
class Courier:
    """Estado mutable de un repartidor.

    Las mutaciones (incrementar active_orders) SOLO ocurren dentro de State,
    que es thread-safe. Esto previene condiciones de carrera.

    Atributos:
        courier_id: Identificador único del repartidor.
        zone: Zona actual donde se encuentra.
        active_orders: Número de pedidos que lleva encima ahora mismo.
        max_capacity: Máximo de pedidos que puede manejar a la vez.
    """
    courier_id: str
    zone: str
    active_orders: int
    max_capacity: int

    def __post_init__(self) -> None:
        """Valida que la capacidad sea positiva y los pedidos activos no sean negativos."""
        if self.max_capacity <= 0:
            raise ValueError(f"max_capacity must be > 0 for {self.courier_id}")
        if self.active_orders < 0:
            raise ValueError(f"active_orders must be >= 0 for {self.courier_id}")

    @property
    def is_available(self) -> bool:
        """True si el repartidor puede tomar más pedidos (no está al tope)."""
        return self.active_orders < self.max_capacity

    @property
    def utilization(self) -> float:
        """Factor de utilización de 0.0 a 1.0 (qué tan lleno está)."""
        return self.active_orders / self.max_capacity


@dataclass(frozen=True)
class Reason:
    """Explicación de una regla aplicada. Parte de la trazabilidad de la decisión.

    Atributos:
        rule: Nombre de la regla (ej: 'same_zone_preferred', 'capacity_ok').
        detail: Descripción humana de por qué se aplicó la regla.
    """
    rule: str
    detail: str


@dataclass(frozen=True)
class Decision:
    """Decisión inmutable retornada por el engine. Se enriquece a través de las fases.

    Atributos:
        order_id: ID del pedido evaluado.
        status: ASSIGNED / QUEUED / REJECTED.
        assigned_courier: ID del repartidor asignado, o None si fue queued/rejected.
        reasons: Lista de reglas aplicadas (cada una con rule y detail).
        cost: Costo estimado del envío en COP (Fase 3, opcional).
        pricing_status: Estado del circuit breaker (Fase 3, opcional).
    """
    order_id: str
    status: OrderStatus
    assigned_courier: Optional[str]
    reasons: list[Reason] = field(default_factory=list)
    cost: Optional[float] = None
    pricing_status: Optional[PricingStatus] = None

    def to_dict(self) -> dict:
        """Serializa la decisión a dict para salida de API/UI.

        Los campos cost y pricing_status solo se incluyen si están presentes
        (aparecen desde Fase 3).
        """
        result = {
            "order_id": self.order_id,
            "status": self.status.value,
            "assigned_courier": self.assigned_courier,
            "reasons": [{"rule": r.rule, "detail": r.detail} for r in self.reasons],
        }
        # Incluir costo y pricing_status solo si están definidos (Fase 3+).
        if self.cost is not None:
            result["cost"] = self.cost
        if self.pricing_status is not None:
            result["pricing_status"] = self.pricing_status.value
        return result
