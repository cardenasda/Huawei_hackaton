"""Aplicación FastAPI — expone el motor FlowMatch sobre HTTP.

Endpoints:
- POST /assign    → asignar un pedido a un courier
- GET  /state     → obtener el estado actual del engine (couriers, cola)
- GET  /health    → health check
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from application.assign_service import AssignOrderUseCase


# ---- Modelos Pydantic para request/response ----

class CourierInput(BaseModel):
    """Modelo de entrada para un courier (en el request de /assign)."""
    courier_id: str
    zone: str
    active_orders: int = 0
    max_capacity: int = Field(gt=0)  # Debe ser > 0.


class AssignRequest(BaseModel):
    """Modelo de request para POST /assign.

    Contiene el pedido + el estado de los couriers (opcional).
    """
    order_id: str
    timestamp: str          # ISO 8601.
    pickup_zone: str
    distance_km: float = Field(ge=0)  # No negativa.
    priority: str           # "normal" | "express".
    couriers: list[CourierInput] = Field(default_factory=list)


def create_app(use_case: AssignOrderUseCase) -> FastAPI:
    """Factory: crea una app FastAPI conectada al caso de uso.

    Usar factory (en lugar de global) facilita el testing y evita
    side effects en tiempo de import.

    Args:
        use_case: El caso de uso de asignación ya configurado.

    Returns:
        Instancia de FastAPI lista para servir.
    """
    app = FastAPI(title="FlowMatch Assignment Engine", version="1.0.0")

    @app.post("/assign")
    async def assign(request: AssignRequest) -> dict:
        """Asigna un pedido a un courier.

        Recibe el pedido + estado de couriers, retorna la decisión
        (status, assigned_courier, reasons, cost, pricing_status).
        """
        try:
            # Delegar al caso de uso.
            result = use_case.execute(request.model_dump())
            return result
        except ValueError as e:
            # Error de validación (pedido inválido).
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            # Error interno inesperado.
            raise HTTPException(status_code=500, detail=f"Internal error: {e}")

    @app.get("/state")
    async def get_state() -> dict:
        """Retorna un snapshot del estado actual del engine."""
        # Acceder al state del engine via el use case.
        engine = use_case._engine  # noqa: SLF001
        return engine._state.snapshot()  # noqa: SLF001

    @app.get("/health")
    async def health() -> dict:
        """Health check endpoint."""
        return {"status": "ok"}

    return app
