"""Cargador de configuración — construye todos los componentes del engine desde settings.

Este es el Composition Root parcial: configura las reglas y parámetros.
El wiring completo de dependencias está en main.py.

Lee de variables de entorno con defaults sensibles.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from domain.pricing import PricingConfig
from domain.rules.capacity import CapacityRule
from domain.rules.least_loaded import LeastLoadedRule
from domain.rules.min_cost import MinCostRule
from domain.rules.same_zone import SameZoneRule
from domain.rules.base import AssignmentRule
from domain.surge import SurgeConfig


@dataclass
class EngineConfig:
    """Configuración top-level que agrega todas las sub-configs.

    Atributos:
        enabled_rules: Lista de reglas habilitadas en orden de ejecución.
        surge: Configuración de surge control.
        pricing: Configuración de pricing + circuit breaker.
        pricing_failure_rate: Tasa de fallo del mock de pricing.
    """
    enabled_rules: list[str] = field(
        default_factory=lambda: ["same_zone", "capacity", "least_loaded", "min_cost"]
    )
    surge: SurgeConfig = field(default_factory=SurgeConfig)
    pricing: PricingConfig = field(default_factory=PricingConfig)
    pricing_failure_rate: float = 0.3

    @classmethod
    def from_env(cls) -> "EngineConfig":
        """Carga la configuración desde variables de entorno.

        Variables soportadas (con defaults):
            COURIER_RATE_MAX=3
            COURIER_RATE_WINDOW=10
            CONTAINMENT_THRESHOLD=3
            CONTAINMENT_DURATION=120
            PRICING_FLAT_RATE_FALLBACK=5000
            PRICING_PER_KM=500
            CB_FAILURE_THRESHOLD=3
            CB_RECOVERY_TIMEOUT=15
            PRICING_FAILURE_RATE=0.3

        Returns:
            EngineConfig con valores de env o defaults.
        """
        # Mapa de zonas vecinas (centro <-> norte <-> sur).
        neighbor_zones = {
            "centro": ["norte", "sur"],
            "norte": ["centro"],
            "sur": ["centro"],
        }
        surge = SurgeConfig(
            courier_rate_max=int(os.getenv("COURIER_RATE_MAX", "3")),
            courier_rate_window_seconds=float(os.getenv("COURIER_RATE_WINDOW", "10")),
            containment_threshold=int(os.getenv("CONTAINMENT_THRESHOLD", "3")),
            containment_duration_seconds=float(os.getenv("CONTAINMENT_DURATION", "120")),
            neighbor_zones=neighbor_zones,
        )
        pricing = PricingConfig(
            base_rate_cop=float(os.getenv("PRICING_FLAT_RATE_FALLBACK", "5000")),
            per_km_rate_cop=float(os.getenv("PRICING_PER_KM", "500")),
            failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "3")),
            recovery_timeout_seconds=float(os.getenv("CB_RECOVERY_TIMEOUT", "15")),
        )
        return cls(
            surge=surge,
            pricing=pricing,
            pricing_failure_rate=float(os.getenv("PRICING_FAILURE_RATE", "0.3")),
        )


def build_rules(config: EngineConfig) -> list[AssignmentRule]:
    """Instancia las reglas habilitadas en el orden configurado.

    Args:
        config: Configuración del engine.

    Returns:
        Lista de instancias de AssignmentRule en orden de ejecución.
    """
    # Mapa de nombres a clases de reglas.
    rule_map = {
        "same_zone": SameZoneRule,
        "capacity": CapacityRule,
        "least_loaded": LeastLoadedRule,
        "min_cost": MinCostRule,
    }
    rules = []
    for name in config.enabled_rules:
        rule_cls = rule_map.get(name)
        if rule_cls:
            rules.append(rule_cls())
    return rules
