"""Adapter de reloj del sistema — tiempo real (wall-clock).

Implementa el port Clock para producción. Retorna el tiempo UTC real.
"""

from __future__ import annotations

from datetime import datetime, timezone

from application.ports.clock import Clock


class SystemClock(Clock):
    """Reloj de producción — retorna el tiempo UTC real.

    En tests se sustituye por FakeClock para controlar el tiempo.
    """

    def now(self) -> datetime:
        """Retorna el datetime UTC actual."""
        return datetime.now(timezone.utc)
