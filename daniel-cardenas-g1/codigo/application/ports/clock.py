"""Port de reloj — abstrae el tiempo para tests deterministas.

Producción usa SystemClock (tiempo real).
Tests usan FakeClock (tiempo controlable) para testar expiraciones y ventanas
sin tener que esperar tiempo real.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    """Interfaz para obtener el tiempo actual.

    Esto permite inyectar un reloj falso en los tests para controlar
    el paso del tiempo de forma determinista.
    """

    @abstractmethod
    def now(self) -> datetime:
        """Retorna el datetime actual (timezone-aware)."""
        ...
