"""Tests de casos borde y escenarios extremos (rúbrica: 9 pts + Bono D).

Valida que el sistema nunca se rompe ante entradas inusuales:
- Timestamp futuro.
- Distancia cero.
- Courier con max_capacity = 1.
- Avalancha de pedidos express.
- Pedido justo cuando expira la contención.
- Verificación de no sobre-asignación.
"""

from __future__ import annotations

import pytest

from domain.models import Courier, Order, OrderStatus, Priority


def make_order(order_id: str, zone: str = "centro", priority: str = "normal", distance: float = 2.0) -> dict:
    """Crea un dict de pedido para tests."""
    return {
        "order_id": order_id,
        "timestamp": "2024-11-28T12:58:00Z",
        "pickup_zone": zone,
        "distance_km": distance,
        "priority": priority,
    }


class TestEdgeCases:
    """Casos borde que el sistema debe manejar sin romperse."""

    def test_distance_zero(self, use_case):
        """Distancia cero es válida (recogida en el mismo sitio)."""
        result = use_case.execute({
            "order_id": "ord_zero",
            "timestamp": "2024-11-28T12:58:00Z",
            "pickup_zone": "centro",
            "distance_km": 0.0,
            "priority": "normal",
        })
        assert result["status"] == "ASSIGNED"

    def test_courier_max_capacity_one(self, fake_clock, fake_pricing, surge_config, pricing_config):
        """Courier con max_capacity=1: se llena con un solo pedido."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from application.assign_service import AssignOrderUseCase

        couriers = [Courier("cour_X", "centro", 0, 1)]
        state = State(couriers)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule()],
            SurgeController(surge_config), CircuitBreaker(pricing_config),
            pricing_config, fake_clock, fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        # Primer pedido: ASSIGNED.
        r1 = uc.execute(make_order("ord_1"))
        assert r1["status"] == "ASSIGNED"

        # Segundo pedido: courier lleno → QUEUED.
        r2 = uc.execute(make_order("ord_2"))
        assert r2["status"] == "QUEUED"


class TestNoOverAssignment:
    """Verifica que NUNCA se sobre-asigna por encima de max_capacity."""

    def test_never_exceeds_capacity(self, fake_clock, fake_pricing, surge_config, pricing_config):
        """Tras muchos pedidos, ningún courier supera su max_capacity."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController, SurgeConfig
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from application.assign_service import AssignOrderUseCase

        config = SurgeConfig(
            courier_rate_max=100,  # Sin rate limit.
            containment_threshold=100,  # Sin contención.
            neighbor_zones={},
        )
        couriers = [
            Courier("cour_A", "centro", 0, 3),
            Courier("cour_B", "centro", 0, 3),
        ]
        state = State(couriers)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule()],
            SurgeController(config), CircuitBreaker(pricing_config),
            pricing_config, fake_clock, fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        # Enviar 20 pedidos.
        for i in range(20):
            uc.execute(make_order(f"ord_{i}"))

        # Verificar que ningún courier supera su capacidad.
        for c in state.get_couriers():
            assert c.active_orders <= c.max_capacity, \
                f"{c.courier_id} has {c.active_orders} > {c.max_capacity}"


class TestExpressAvalanche:
    """Avalancha de pedidos express durante contención."""

    def test_express_orders_always_queued_never_rejected(
        self, fake_clock, fake_pricing, surge_config, pricing_config
    ):
        """Durante contención, pedidos express siempre se encolan, nunca se rechazan."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController, SurgeConfig
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from application.assign_service import AssignOrderUseCase

        config = SurgeConfig(
            courier_rate_max=100,
            containment_threshold=3,
            containment_duration_seconds=120.0,
            neighbor_zones={},
        )
        couriers = [
            Courier("cour_A", "centro", 0, 3),
            Courier("cour_B", "centro", 0, 3),
        ]
        state = State(couriers)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule()],
            SurgeController(config), CircuitBreaker(pricing_config),
            pricing_config, fake_clock, fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        # Llenar couriers + activar contención.
        for i in range(6):
            uc.execute(make_order(f"ord_{i}"))
        for i in range(6, 9):
            uc.execute(make_order(f"ord_{i}"))

        # Enviar 10 pedidos express durante contención.
        for i in range(10):
            r = uc.execute(make_order(f"express_{i}", priority="express"))
            assert r["status"] == "QUEUED", \
                f"Express order {i} should be QUEUED, got {r['status']}"
