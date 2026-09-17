"""Interfaz base para las reglas de asignación (Strategy pattern).

Cada regla implementa esta interfaz. El engine las encadena en orden configurable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..models import Courier, Order, Reason
from ..state import State


@dataclass
class RuleResult:
    """Resultado de aplicar una regla a una lista de candidatos.

    Atributos:
        candidates: Candidatos restantes después de esta regla.
        reason: Explicación opcional de qué hizo esta regla (para trazabilidad).
    """
    candidates: list[Courier]
    reason: Optional[Reason] = None


class AssignmentRule(ABC):
    """Regla abstracta. Las subclases implementan la lógica de filtrado/ordenamiento.

    El engine llama a apply() en secuencia. Cada regla recibe los candidatos
    filtrados por las reglas anteriores y retorna una nueva lista (filtrada u ordenada).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador de la regla (usado en reasons y configuración)."""
        ...

    @abstractmethod
    def apply(
        self, order: Order, candidates: list[Courier], state: State
    ) -> RuleResult:
        """Aplica esta regla a la lista de candidatos.

        Args:
            order: El pedido siendo asignado.
            candidates: Candidatos actuales (ya filtrados por reglas anteriores).
            state: Estado compartido del engine (read-only para la mayoría de reglas).

        Returns:
            RuleResult con candidatos filtrados/ordenados y un reason explicativo.
        """
        ...
