"""Tests para Fase 1 — asignación base por prioridad.

Valida el ejemplo exacto del enunciado del Reto 2.
"""

from __future__ import annotations

import pytest

from domain.models import Order, OrderStatus, Priority


class TestFase1BaseAssignment:
    """Tests que coinciden con el ejemplo de la Fase 1 del enunciado."""

    def test_example_order_assigned_to_cour_a(self, use_case, sample_order_data):
        """El ejemplo del enunciado: pedido express en centro → ASSIGNED a cour_A."""
        result = use_case.execute(sample_order_data)

        assert result["order_id"] == "ord_00234"
        assert result["status"] == "ASSIGNED"
        assert result["assigned_courier"] == "cour_A"

    def test_reasons_contain_same_zone(self, use_case, sample_order_data):
        """Las reasons deben incluir la regla same_zone_preferred."""
        result = use_case.execute(sample_order_data)
        rules = [r["rule"] for r in result["reasons"]]

        assert "same_zone_preferred" in rules

    def test_reasons_contain_capacity_ok(self, use_case, sample_order_data):
        """Las reasons deben incluir capacity_ok mostrando cour_C saltado."""
        result = use_case.execute(sample_order_data)
        capacity_reason = next(
            r for r in result["reasons"] if r["rule"] == "capacity_ok"
        )

        assert "cour_C" in capacity_reason["detail"]
        assert "full" in capacity_reason["detail"]

    def test_reasons_contain_least_loaded(self, use_case, sample_order_data):
        """Las reasons deben incluir least_loaded."""
        result = use_case.execute(sample_order_data)
        rules = [r["rule"] for r in result["reasons"]]

        assert "least_loaded" in rules

    def test_courier_active_orders_incremented(self, use_case, sample_order_data):
        """Después de asignar, cour_A.active_orders debe ser 2 (era 1)."""
        use_case.execute(sample_order_data)
        engine = use_case._engine  # noqa: SLF001
        cour_a = engine._state.get_courier("cour_A")  # noqa: SLF001

        assert cour_a.active_orders == 2


class TestFase1AllCouriersFull:
    """Cuando todos los couriers están a capacidad → QUEUED."""

    def test_all_full_queues_order(self, use_case, sample_order_data):
        """Llenar todos los couriers, luego un pedido nuevo debe ser QUEUED."""
        engine = use_case._engine  # noqa: SLF001
        # Llenar cour_A (1/3 → 3/3).
        engine._state.assign_to_courier("cour_A")  # noqa: SLF001
        engine._state.assign_to_courier("cour_A")  # noqa: SLF001
        # Llenar cour_B (0/3 → 3/3).
        engine._state.assign_to_courier("cour_B")  # noqa: SLF001
        engine._state.assign_to_courier("cour_B")  # noqa: SLF001
        engine._state.assign_to_courier("cour_B")  # noqa: SLF001
        # cour_C ya está 3/3.

        result = use_case.execute(sample_order_data)

        assert result["status"] == "QUEUED"
        assert result["assigned_courier"] is None


class TestFase1NoCouriers:
    """Caso borde: sin couriers disponibles."""

    def test_no_couriers_rejects(self, fake_clock, fake_pricing, surge_config, pricing_config):
        """Con cero couriers, el pedido debe ser QUEUED (no hay a quién asignar)."""
        from domain.engine import AssignmentEngine
        from domain.state import State
        from domain.surge import SurgeController
        from domain.pricing import CircuitBreaker
        from domain.rules.same_zone import SameZoneRule
        from domain.rules.capacity import CapacityRule
        from domain.rules.least_loaded import LeastLoadedRule
        from application.assign_service import AssignOrderUseCase

        state = State([])  # Sin couriers.
        engine = AssignmentEngine(
            state,
            [SameZoneRule(), CapacityRule(), LeastLoadedRule()],
            SurgeController(surge_config),
            CircuitBreaker(pricing_config),
            pricing_config,
            fake_clock,
            fake_pricing,
        )
        uc = AssignOrderUseCase(engine)

        result = uc.execute({
            "order_id": "ord_empty",
            "timestamp": "2024-11-28T12:58:00Z",
            "pickup_zone": "centro",
            "distance_km": 1.0,
            "priority": "normal",
        })

        assert result["status"] == "QUEUED"
        assert result["assigned_courier"] is None


class TestFase1Validation:
    """Validación de entradas — casos borde (rúbrica: 9 pts)."""

    def test_negative_distance_raises(self, use_case):
        """Distancia negativa → ValueError."""
        with pytest.raises(ValueError, match="distance_km"):
            use_case.execute({
                "order_id": "ord_neg",
                "timestamp": "2024-11-28T12:58:00Z",
                "pickup_zone": "centro",
                "distance_km": -1.0,
                "priority": "normal",
            })

    def test_invalid_priority_raises(self, use_case):
        """Prioridad inválida → ValueError."""
        with pytest.raises(ValueError):
            use_case.execute({
                "order_id": "ord_bad",
                "timestamp": "2024-11-28T12:58:00Z",
                "pickup_zone": "centro",
                "distance_km": 1.0,
                "priority": "urgent",  # Inválida.
            })

    def test_empty_order_id_raises(self, use_case):
        """order_id vacío → ValueError."""
        with pytest.raises(ValueError, match="order_id"):
            use_case.execute({
                "order_id": "",
                "timestamp": "2024-11-28T12:58:00Z",
                "pickup_zone": "centro",
                "distance_km": 1.0,
                "priority": "normal",
            })
