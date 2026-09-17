"""Composition Root — wiring de todas las dependencias y entry points.

Este es el ÚNICO lugar que conoce las implementaciones concretas.
Todo lo demás depende de abstracciones (ports).

Uso:
    # Iniciar el servidor API
    python main.py api

    # Asignar un solo pedido (CLI)
    python main.py assign --order '{"order_id": "ord_001", ...}'

    # Ejecutar el demo del enunciado
    python main.py demo

    # Iniciar la UI de Streamlit
    streamlit run presentation/streamlit_app.py
"""

from __future__ import annotations

import json
import sys

from domain.engine import AssignmentEngine
from domain.models import Courier
from domain.pricing import CircuitBreaker
from domain.state import State
from domain.surge import SurgeController
from application.assign_service import AssignOrderUseCase
from infrastructure.config import EngineConfig, build_rules
from infrastructure.mock_pricing import MockPricing
from infrastructure.system_clock import SystemClock


# ---- Couriers por defecto (ejemplo del Reto 2) ----
DEFAULT_COURIERS = [
    Courier(courier_id="cour_A", zone="centro", active_orders=1, max_capacity=3),
    Courier(courier_id="cour_B", zone="norte", active_orders=0, max_capacity=3),
    Courier(courier_id="cour_C", zone="centro", active_orders=3, max_capacity=3),
]


def build_engine(
    couriers: list[Courier] | None = None,
    config: EngineConfig | None = None,
    pricing_seed: int = 42,
) -> AssignmentEngine:
    """Construye un engine con todas las dependencias inyectadas (DI wiring).

    Args:
        couriers: Estado inicial de couriers (default: ejemplo del Reto 2).
        config: Configuración del engine (default: desde env vars).
        pricing_seed: Seed aleatorio para mock pricing determinista.

    Returns:
        AssignmentEngine listo para usar.
    """
    if config is None:
        config = EngineConfig.from_env()
    if couriers is None:
        couriers = DEFAULT_COURIERS

    # Wiring de dependencias.
    state = State(couriers)
    rules = build_rules(config)
    surge = SurgeController(config.surge)
    cb = CircuitBreaker(config.pricing)
    clock = SystemClock()
    pricing = MockPricing(
        failure_rate=config.pricing_failure_rate,
        base_rate=config.pricing.base_rate_cop,
        per_km_rate=config.pricing.per_km_rate_cop,
        seed=pricing_seed,
    )
    return AssignmentEngine(state, rules, surge, cb, config.pricing, clock, pricing)


def build_use_case(
    couriers: list[Courier] | None = None,
    config: EngineConfig | None = None,
    pricing_seed: int = 42,
) -> AssignOrderUseCase:
    """Construye un caso de uso con todas las dependencias inyectadas.

    Args:
        couriers: Estado inicial de couriers.
        config: Configuración del engine.
        pricing_seed: Seed para mock pricing.

    Returns:
        AssignOrderUseCase listo para usar.
    """
    engine = build_engine(couriers, config, pricing_seed)
    return AssignOrderUseCase(engine)


# ---- CLI entry point ----

def main() -> None:
    """Entry point CLI.

    Comandos:
        api      → iniciar servidor FastAPI (uvicorn)
        assign   → asignar un solo pedido desde JSON arg
        demo     → ejecutar el ejemplo del Reto 2
    """
    if len(sys.argv) < 2:
        print("Usage: python main.py [api|assign|demo]")
        print("  api    - start the FastAPI server")
        print("  assign - assign an order (pass JSON as next arg)")
        print("  demo   - run the Reto 2 example order")
        sys.exit(1)

    command = sys.argv[1]

    if command == "demo":
        # Ejecutar el ejemplo del enunciado.
        use_case = build_use_case()
        order = {
            "order_id": "ord_00234",
            "timestamp": "2024-11-28T12:58:00Z",
            "pickup_zone": "centro",
            "distance_km": 3.2,
            "priority": "express",
        }
        result = use_case.execute(order)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif command == "assign":
        # Asignar un pedido desde JSON.
        if len(sys.argv) < 3:
            print("Usage: python main.py assign '<json_order>'")
            sys.exit(1)
        use_case = build_use_case()
        order = json.loads(sys.argv[2])
        result = use_case.execute(order)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif command == "api":
        # Iniciar el servidor FastAPI.
        import uvicorn
        from infrastructure.api.main import create_app

        use_case = build_use_case()
        app = create_app(use_case)
        uvicorn.run(app, host="0.0.0.0", port=8000)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
