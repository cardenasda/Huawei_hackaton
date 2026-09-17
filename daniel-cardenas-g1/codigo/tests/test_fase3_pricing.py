"""Tests para Fase 3 — optimización de costo + circuit breaker.

Valida:
- El costo se computa correctamente (base + per_km * distance).
- El circuit breaker abre tras 3 fallos consecutivos.
- Cuando el circuito está abierto, se usa tarifa base fija (degradación segura).
- Tras recovery_timeout, el circuito pasa a half-open y permite una prueba.
- La decisión incluye cost y pricing_status.
"""

from __future__ import annotations

import pytest

from domain.models import Courier, Order, OrderStatus, PricingStatus


def make_order(order_id: str = "ord_test", priority: str = "normal") -> dict:
    """Crea un dict de pedido para tests de Fase 3."""
    return {
        "order_id": order_id,
        "timestamp": "2024-11-28T12:58:00Z",
        "pickup_zone": "centro",
        "distance_km": 3.2,
        "priority": priority,
    }


class TestCostComputation:
    """Verifica que el costo se computa correctamente."""

    def test_decision_includes_cost(self, use_case, sample_order_data):
        """La decisión debe incluir el campo cost."""
        result = use_case.execute(sample_order_data)
        assert "cost" in result
        assert result["cost"] is not None
        assert result["cost"] > 0

    def test_decision_includes_pricing_status(self, use_case, sample_order_data):
        """La decisión debe incluir el campo pricing_status."""
        result = use_case.execute(sample_order_data)
        assert "pricing_status" in result
        assert result["pricing_status"] is not None


class TestCircuitBreaker:
    """Tests del circuit breaker con FakePricing controlable."""

    @pytest.fixture
    def cb_engine(self, fake_clock, surge_config, pricing_config):
        """Engine con FakePricing que puede fallar on-demand."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from domain.rules.min_cost import MinCostRule
        from application.assign_service import AssignOrderUseCase
        from tests.conftest import FakePricing

        couriers = [
            Courier("cour_A", "centro", 0, 10),
            Courier("cour_B", "centro", 0, 10),
        ]
        state = State(couriers)
        surge = SurgeController(surge_config)
        cb = CircuitBreaker(pricing_config)
        # FakePricing que falla por defecto.
        pricing = FakePricing(price=6800.0, fail=True)
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule(), MinCostRule()],
            surge, cb, pricing_config, fake_clock, pricing,
        )
        return AssignOrderUseCase(engine), fake_clock, cb, pricing

    def test_circuit_opens_after_threshold_failures(self, cb_engine):
        """Tras 3 fallos consecutivos, el circuito se abre."""
        uc, clock, cb, pricing = cb_engine

        # 3 pedidos → 3 fallos del pricing → circuito abre.
        for i in range(3):
            uc.execute(make_order(f"ord_{i}"))

        # El circuito debe estar abierto (degraded flat rate).
        status = cb.get_status()
        assert status == PricingStatus.CIRCUIT_OPEN_DEGRADED_FLAT_RATE

    def test_degraded_flat_rate_when_open(self, cb_engine, pricing_config):
        """Cuando el circuito está abierto, se usa tarifa base fija."""
        uc, clock, cb, pricing = cb_engine

        # Provocar 3 fallos para abrir el circuito.
        for i in range(3):
            uc.execute(make_order(f"ord_{i}"))

        # 4to pedido: circuito abierto → tarifa base fija.
        result = uc.execute(make_order("ord_degraded"))
        assert result["cost"] == pricing_config.base_rate_cop
        assert result["pricing_status"] == "circuit_open_degraded_flat_rate"

    def test_circuit_half_open_after_recovery(self, cb_engine, pricing_config):
        """Tras recovery_timeout, el circuito pasa a half-open."""
        uc, clock, cb, pricing = cb_engine

        # Abrir el circuito con 3 fallos.
        for i in range(3):
            uc.execute(make_order(f"ord_{i}"))

        # Avanzar más allá del recovery_timeout (15s).
        clock.advance(16)

        # Hacer que el pricing funcione ahora.
        pricing.set_fail(False)

        # Siguiente pedido: half-open → prueba → éxito → closed.
        result = uc.execute(make_order("ord_recover"))
        assert result["status"] == "ASSIGNED"
        assert result["pricing_status"] == "ok"

    def test_circuit_reopens_if_half_open_fails(self, cb_engine):
        """Si la prueba half-open falla, el circuito vuelve a open."""
        uc, clock, cb, pricing = cb_engine

        # Abrir el circuito.
        for i in range(3):
            uc.execute(make_order(f"ord_{i}"))

        # Avanzar más allá del recovery_timeout.
        clock.advance(16)

        # El pricing sigue fallando → half-open → fallo → open.
        result = uc.execute(make_order("ord_reopen"))
        assert cb.get_status() == PricingStatus.CIRCUIT_OPEN_DEGRADED_FLAT_RATE

    def test_assignment_succeeds_even_if_pricing_fails(self, cb_engine):
        """La asignación NO falla aunque el pricing falle (degradación segura)."""
        uc, clock, cb, pricing = cb_engine

        # Todos los pedidos se asignan aunque el pricing falle.
        for i in range(5):
            result = uc.execute(make_order(f"ord_{i}"))
            assert result["status"] == "ASSIGNED"
