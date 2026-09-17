"""Fixtures compartidas + fakes para tests deterministas.

Fakes clave:
- FakeClock: tiempo controlable para testar expiraciones y sliding windows.
- FakePricing: servicio de pricing controlable (nunca falla salvo que se le indique).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.engine import AssignmentEngine
from domain.models import Courier, Order
from domain.pricing import CircuitBreaker, PricingConfig
from domain.state import State
from domain.surge import SurgeController, SurgeConfig
from domain.rules.capacity import CapacityRule
from domain.rules.least_loaded import LeastLoadedRule
from domain.rules.min_cost import MinCostRule
from domain.rules.same_zone import SameZoneRule
from application.assign_service import AssignOrderUseCase
from application.ports.clock import Clock
from application.ports.pricing import PricingService


# ---- Fakes ----

class FakeClock(Clock):
    """Reloj controlable para tests deterministas.

    Permite avanzar el tiempo manualmente sin esperar tiempo real.
    """
    def __init__(self, start: datetime | None = None) -> None:
        """Inicializa con un tiempo de inicio (default: 2024-11-28 12:58 UTC)."""
        self._time = start or datetime(2024, 11, 28, 12, 58, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """Retorna el tiempo actual del fake."""
        return self._time

    def advance(self, seconds: float) -> None:
        """Avanza el tiempo del fake en N segundos."""
        from datetime import timedelta
        self._time += timedelta(seconds=seconds)

    def set(self, dt: datetime) -> None:
        """Establece el tiempo del fake a un valor específico."""
        self._time = dt


class FakePricing(PricingService):
    """Servicio de pricing controlable que nunca falla salvo que se configure.

    Permite tests deterministas del circuit breaker.
    """
    def __init__(self, price: float = 6800.0, fail: bool = False) -> None:
        """Inicializa con un precio fijo y flag de fallo.

        Args:
            price: Precio a retornar cuando no falla.
            fail: Si True, siempre lanza excepción.
        """
        self._price = price
        self._fail = fail
        self.call_count = 0  # Contador de llamadas (para verificar en tests).

    def get_price(self, order: Order, now: datetime) -> float:
        """Retorna el precio fijo, o lanza excepción si fail=True."""
        self.call_count += 1
        if self._fail:
            raise ConnectionError("forced failure")
        return self._price

    def set_fail(self, fail: bool) -> None:
        """Cambia el flag de fallo (para tests que necesitan alternar)."""
        self._fail = fail


# ---- Fixtures ----

@pytest.fixture
def fake_clock() -> FakeClock:
    """Reloj fake para tests deterministas."""
    return FakeClock()


@pytest.fixture
def fake_pricing() -> FakePricing:
    """Pricing fake que siempre funciona (precio fijo 6800)."""
    return FakePricing()


@pytest.fixture
def default_couriers() -> list[Courier]:
    """Couriers del ejemplo del Reto 2 (cour_A 1/3, cour_B 0/3, cour_C 3/3)."""
    return [
        Courier(courier_id="cour_A", zone="centro", active_orders=1, max_capacity=3),
        Courier(courier_id="cour_B", zone="norte", active_orders=0, max_capacity=3),
        Courier(courier_id="cour_C", zone="centro", active_orders=3, max_capacity=3),
    ]


@pytest.fixture
def surge_config() -> SurgeConfig:
    """Configuración de surge para tests (rate limit 3/10s, contención 3/120s)."""
    return SurgeConfig(
        courier_rate_max=3,
        courier_rate_window_seconds=10.0,
        containment_threshold=3,
        containment_duration_seconds=120.0,
        neighbor_zones={"centro": ["norte", "sur"], "norte": ["centro"], "sur": ["centro"]},
    )


@pytest.fixture
def pricing_config() -> PricingConfig:
    """Configuración de pricing para tests (base 5000, per_km 500, CB 3/15s)."""
    return PricingConfig(
        base_rate_cop=5000.0,
        per_km_rate_cop=500.0,
        failure_threshold=3,
        recovery_timeout_seconds=15.0,
    )


@pytest.fixture
def all_rules() -> list:
    """Todas las 4 reglas en orden de ejecución."""
    return [SameZoneRule(), CapacityRule(), LeastLoadedRule(), MinCostRule()]


@pytest.fixture
def engine(
    default_couriers: list[Courier],
    all_rules: list,
    surge_config: SurgeConfig,
    pricing_config: PricingConfig,
    fake_clock: FakeClock,
    fake_pricing: FakePricing,
) -> AssignmentEngine:
    """Engine con fakes para tests deterministas."""
    state = State(default_couriers)
    surge = SurgeController(surge_config)
    cb = CircuitBreaker(pricing_config)
    return AssignmentEngine(state, all_rules, surge, cb, pricing_config, fake_clock, fake_pricing)


@pytest.fixture
def use_case(engine: AssignmentEngine) -> AssignOrderUseCase:
    """Caso de uso con engine de test."""
    return AssignOrderUseCase(engine)


@pytest.fixture
def sample_order_data() -> dict:
    """Order de ejemplo del Reto 2 como dict crudo."""
    return {
        "order_id": "ord_00234",
        "timestamp": "2024-11-28T12:58:00Z",
        "pickup_zone": "centro",
        "distance_km": 3.2,
        "priority": "express",
    }
