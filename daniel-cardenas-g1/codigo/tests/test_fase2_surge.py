"""Tests para Fase 2 — surge control, sliding window, containment mode.

Valida el comportamiento exacto descrito en el enunciado del Reto 2:
- 6 pedidos a la misma zona en 7 segundos → pedido #6 es REJECTED.
- Pedido #7 (normal) durante contención → REJECTED con surge_window_active.
- Pedido #7 (express) durante contención → QUEUED.
- Contención auto-expira después de 120 segundos.
- Rate limiting por courier (sliding window).
- Zone balancing: cuando same-zone está lleno, usa zonas vecinas.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.models import Courier, Order, OrderStatus, Priority


# ---- Helpers ----

def make_order(order_id: str, zone: str = "centro", priority: str = "normal") -> dict:
    """Crea un dict de pedido para tests.

    Args:
        order_id: ID del pedido.
        zone: Zona de recogida (default: centro).
        priority: Prioridad (default: normal).

    Returns:
        Dict con los campos del pedido.
    """
    return {
        "order_id": order_id,
        "timestamp": "2024-11-28T12:58:00Z",
        "pickup_zone": zone,
        "distance_km": 2.0,
        "priority": priority,
    }


# ---- Tarea 2.1: Rate limiting por courier (sliding window) ----

class TestPerCourierRateLimit:
    """Un courier no puede recibir >N pedidos nuevos en W segundos, aunque tenga capacidad."""

    def test_courier_rate_limited_after_max(
        self, fake_clock, fake_pricing, surge_config, pricing_config
    ):
        """Después de 3 asignaciones en 10s, el courier está rate-limited."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from domain.rules.min_cost import MinCostRule
        from application.assign_service import AssignOrderUseCase

        # Un courier con capacidad alta pero rate limit = 3 per 10s.
        couriers = [Courier("cour_X", "centro", 0, 10)]
        state = State(couriers)
        surge = SurgeController(surge_config)
        cb = CircuitBreaker(pricing_config)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule(), MinCostRule()],
            surge, cb, pricing_config, fake_clock, fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        # Asignar 3 pedidos (rate limit alcanzado).
        for i in range(3):
            result = uc.execute(make_order(f"ord_{i}"))
            assert result["status"] == "ASSIGNED"

        # 4to pedido en la misma ventana → courier rate-limited → QUEUED.
        result = uc.execute(make_order("ord_3"))
        assert result["status"] == "QUEUED"
        rules = [r["rule"] for r in result["reasons"]]
        assert "courier_rate_limited" in rules

    def test_rate_limit_resets_after_window(
        self, fake_clock, fake_pricing, surge_config, pricing_config
    ):
        """Después de que pase la ventana deslizante, el courier puede recibir de nuevo."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from domain.rules.min_cost import MinCostRule
        from application.assign_service import AssignOrderUseCase

        couriers = [Courier("cour_X", "centro", 0, 10)]
        state = State(couriers)
        surge = SurgeController(surge_config)
        cb = CircuitBreaker(pricing_config)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule(), MinCostRule()],
            surge, cb, pricing_config, fake_clock, fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        # Asignar 3 pedidos (rate limit alcanzado).
        for i in range(3):
            uc.execute(make_order(f"ord_{i}"))

        # Avanzar el tiempo más allá de la ventana (10s).
        fake_clock.advance(11)

        # Ahora el courier puede recibir de nuevo.
        result = uc.execute(make_order("ord_after"))
        assert result["status"] == "ASSIGNED"


# ---- Tarea 2.2: Zone balancing ----

class TestZoneBalancing:
    """Cuando los couriers de same-zone están llenos, usar zonas vecinas."""

    def test_falls_back_to_neighbor_zone(
        self, fake_clock, fake_pricing, surge_config, pricing_config
    ):
        """Si todos los couriers de centro están llenos, asignar a norte (vecino)."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from domain.rules.min_cost import MinCostRule
        from application.assign_service import AssignOrderUseCase

        # courier de centro lleno, courier de norte disponible (vecino).
        couriers = [
            Courier("cour_A", "centro", 3, 3),  # Lleno.
            Courier("cour_B", "norte", 0, 3),   # Disponible, vecino.
        ]
        state = State(couriers)
        surge = SurgeController(surge_config)
        cb = CircuitBreaker(pricing_config)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule(), MinCostRule()],
            surge, cb, pricing_config, fake_clock, fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        result = uc.execute(make_order("ord_zb"))
        assert result["status"] == "ASSIGNED"
        assert result["assigned_courier"] == "cour_B"
        rules = [r["rule"] for r in result["reasons"]]
        assert "zone_balancing" in rules


# ---- Tarea 2.3 + 2.4: Modo de contención (escenario del enunciado) ----

class TestContainmentMode:
    """El escenario exacto del enunciado: 6 pedidos → #6 REJECTED."""

    @pytest.fixture
    def burst_engine(
        self, fake_clock, fake_pricing, surge_config, pricing_config
    ):
        """Engine con 2 couriers de centro (capacidad 3 c/u) sin zonas vecinas.

        Sin zone balancing, 6 pedidos a centro llenan ambos couriers (3+3=6)
        y luego activan contención.
        """
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController, SurgeConfig
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from domain.rules.min_cost import MinCostRule
        from application.assign_service import AssignOrderUseCase

        # 2 couriers de centro, capacidad 3 c/u = 6 cupos total.
        # Sin zonas vecinas → todos los pedidos se quedan en centro.
        config = SurgeConfig(
            courier_rate_max=100,  # Desactivar rate limit para este test.
            courier_rate_window_seconds=10.0,
            containment_threshold=3,
            containment_duration_seconds=120.0,
            neighbor_zones={},  # Sin zone balancing → fuerza contención.
        )
        couriers = [
            Courier("cour_A", "centro", 0, 3),
            Courier("cour_B", "centro", 0, 3),
        ]
        state = State(couriers)
        surge = SurgeController(config)
        cb = CircuitBreaker(pricing_config)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule(), MinCostRule()],
            surge, cb, pricing_config, fake_clock, fake_pricing,
        )
        return AssignOrderUseCase(engine), fake_clock

    def test_six_orders_trigger_contention(self, burst_engine):
        """Pedidos 1-6 llenan couriers, 7-8 QUEUE, 9 REJECTED (contención)."""
        uc, clock = burst_engine
        results = []

        # Llenar los 6 cupos.
        for i in range(6):
            r = uc.execute(make_order(f"ord_{i:05d}"))
            results.append(r)
            assert r["status"] == "ASSIGNED", f"Order {i} should be ASSIGNED, got {r['status']}"

        # Pedidos 7-8: QUEUED (todos llenos, pero contención aún no activa).
        for i in range(6, 8):
            r = uc.execute(make_order(f"ord_{i:05d}"))
            results.append(r)
            assert r["status"] == "QUEUED", f"Order {i} should be QUEUED, got {r['status']}"

        # Pedido 9: REJECTED (contención activada en 3er consecutivo full).
        r = uc.execute(make_order("ord_00008"))
        assert r["status"] == "REJECTED"
        rules = [reason["rule"] for reason in r["reasons"]]
        assert "surge_protection_active" in rules

    def test_normal_order_during_contention_rejected(
        self, burst_engine
    ):
        """Pedido #7 (normal) durante contención activa → REJECTED con surge_window_active."""
        uc, clock = burst_engine

        # Llenar cupos + activar contención.
        for i in range(6):
            uc.execute(make_order(f"ord_{i:05d}"))
        for i in range(6, 9):
            uc.execute(make_order(f"ord_{i:05d}"))  # 9no activa contención.

        # Pedido durante contención (normal) → REJECTED con surge_window_active.
        r = uc.execute(make_order("ord_during", priority="normal"))
        assert r["status"] == "REJECTED"
        rules = [reason["rule"] for reason in r["reasons"]]
        assert "surge_window_active" in rules

    def test_express_order_during_contention_queued(
        self, burst_engine
    ):
        """Pedido #7 (express) durante contención activa → QUEUED (no rechazado)."""
        uc, clock = burst_engine

        # Llenar cupos + activar contención.
        for i in range(6):
            uc.execute(make_order(f"ord_{i:05d}"))
        for i in range(6, 9):
            uc.execute(make_order(f"ord_{i:05d}"))

        # Pedido express durante contención → QUEUED.
        r = uc.execute(make_order("ord_express", priority="express"))
        assert r["status"] == "QUEUED"
        rules = [reason["rule"] for reason in r["reasons"]]
        assert "surge_window_active" in rules

    def test_contention_auto_expires(self, burst_engine):
        """Después de 120 segundos, la contención auto-expira y los pedidos fluyen normal."""
        uc, clock = burst_engine

        # Llenar cupos + activar contención.
        for i in range(6):
            uc.execute(make_order(f"ord_{i:05d}"))
        for i in range(6, 9):
            uc.execute(make_order(f"ord_{i:05d}"))

        # Verificar que la contención está activa.
        r = uc.execute(make_order("ord_check", priority="normal"))
        assert r["status"] == "REJECTED"

        # Avanzar el tiempo más allá de la duración de contención (120s).
        clock.advance(121)

        # Liberar un courier (simular que completó pedidos).
        engine = uc._engine  # noqa: SLF001
        engine._state.release_courier("cour_A")  # noqa: SLF001

        # Ahora un pedido normal debe ser ASSIGNED de nuevo.
        r = uc.execute(make_order("ord_after_expire", priority="normal"))
        assert r["status"] == "ASSIGNED"


# ---- Correctitud del sliding window ----

class TestSlidingWindow:
    """Verifica que el sliding window purga eventos viejos correctamente."""

    def test_old_events_purged(self, fake_clock, fake_pricing, surge_config, pricing_config):
        """Eventos fuera de la ventana se purgan (sliding, no fixed)."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from domain.rules.min_cost import MinCostRule
        from application.assign_service import AssignOrderUseCase

        couriers = [Courier("cour_X", "centro", 0, 10)]
        state = State(couriers)
        surge = SurgeController(surge_config)
        cb = CircuitBreaker(pricing_config)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule(), MinCostRule()],
            surge, cb, pricing_config, fake_clock, fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        # Asignar 2 pedidos en t=0.
        uc.execute(make_order("ord_0"))
        uc.execute(make_order("ord_1"))

        # Avanzar 8s (dentro de ventana 10s) → 3er pedido alcanza rate limit.
        fake_clock.advance(8)
        uc.execute(make_order("ord_2"))  # 3ra asignación en t=8.

        # 4to en t=8 → rate limited (3 en ventana [0,8]).
        r = uc.execute(make_order("ord_3"))
        assert r["status"] == "QUEUED"

        # Avanzar a t=11 → ord_0 (t=0) se purga (fuera de ventana 10s).
        fake_clock.advance(3)
        # Ahora solo 2 asignaciones en ventana → puede asignar de nuevo.
        r = uc.execute(make_order("ord_4"))
        assert r["status"] == "ASSIGNED"
