"""UI Streamlit — Fase 4: interfaz de verificación visual.

Ejecutar con: streamlit run presentation/streamlit_app.py

Features:
- Formulario para enviar un pedido (sin JSON/curl/Postman).
- Visualizar la decisión con status color-coded (🟢/🟡/🔴).
- Botón para simular una ráfaga (N pedidos a la misma zona).
- Editor de estado de couriers en el sidebar.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone

# Añadir el directorio padre al path para imports cuando se ejecuta standalone.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from domain.models import Courier, Order, OrderStatus, Priority
from application.assign_service import AssignOrderUseCase


def _status_color(status: str) -> str:
    """Retorna emoji según el status para visualización color-coded.

    Args:
        status: El status del pedido (ASSIGNED/QUEUED/REJECTED).

    Returns:
        Emoji: 🟢 (ASSIGNED), 🟡 (QUEUED), 🔴 (REJECTED).
    """
    if status == OrderStatus.ASSIGNED.value:
        return "🟢"  # Verde: asignado.
    if status == OrderStatus.QUEUED.value:
        return "🟡"  # Amarillo: en cola.
    return "🔴"  # Rojo: rechazado.


def _render_decision(decision_dict: dict) -> None:
    """Renderiza una decisión con color y detalles.

    Muestra: status (con emoji), courier asignado, costo, y desglose de reglas.

    Args:
        decision_dict: La decisión serializada como dict.
    """
    status = decision_dict.get("status", "UNKNOWN")
    emoji = _status_color(status)
    courier = decision_dict.get("assigned_courier", "—")
    cost = decision_dict.get("cost")

    # Mostrar status + courier con emoji.
    st.markdown(f"### {emoji} {status} → {courier}")
    if cost is not None:
        st.markdown(f"**Costo:** ${cost:,.0f} COP")
    if decision_dict.get("pricing_status"):
        st.markdown(f"**Pricing:** `{decision_dict['pricing_status']}`")

    # Mostrar desglose de reglas aplicadas.
    st.markdown("**Reglas aplicadas:**")
    for r in decision_dict.get("reasons", []):
        st.markdown(f"- `{r['rule']}`: {r['detail']}")


def main(use_case: AssignOrderUseCase) -> None:
    """UI principal de Streamlit. Recibe un use case ya configurado.

    Args:
        use_case: El caso de uso de asignación con todas las dependencias inyectadas.
    """
    st.set_page_config(page_title="FlowMatch Engine", page_icon="🚀", layout="wide")
    st.title("🚀 FlowMatch Assignment Engine")
    st.caption("Reto 2 — Asignación de pedidos a repartidores en tiempo real")

    # ---- Sidebar: estado de couriers ----
    st.sidebar.header("🛵 Repartidores (estado inicial)")
    if "couriers_initialized" not in st.session_state:
        # Couriers por defecto (ejemplo del enunciado).
        st.session_state.couriers_initialized = True
        st.session_state.couriers = [
            {"courier_id": "cour_A", "zone": "centro", "active_orders": 1, "max_capacity": 3},
            {"courier_id": "cour_B", "zone": "norte", "active_orders": 0, "max_capacity": 3},
            {"courier_id": "cour_C", "zone": "centro", "active_orders": 3, "max_capacity": 3},
        ]

    # Editor de couriers en el sidebar.
    edited_couriers = []
    for i, c in enumerate(st.session_state.couriers):
        with st.sidebar.expander(f"{c['courier_id']} ({c['zone']})", expanded=False):
            c["zone"] = st.selectbox("Zona", ["centro", "norte", "sur"], key=f"zone_{i}", index=["centro", "norte", "sur"].index(c["zone"]))
            c["active_orders"] = st.number_input("Pedidos activos", 0, 10, c["active_orders"], key=f"ao_{i}")
            c["max_capacity"] = st.number_input("Capacidad máx", 1, 10, c["max_capacity"], key=f"mc_{i}")
            edited_couriers.append(c)

    # ---- Main: formulario de pedido ----
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📝 Nuevo pedido")
        # Campos del formulario.
        order_id = st.text_input("Order ID", value=f"ord_{int(datetime.now().timestamp()) % 100000:05d}")
        pickup_zone = st.selectbox("Zona de recogida", ["centro", "norte", "sur"])
        distance_km = st.number_input("Distancia (km)", 0.0, 100.0, 3.2, 0.1)
        priority = st.selectbox("Prioridad", ["normal", "express"])

        if st.button("✅ Asignar", type="primary"):
            # Construir y enviar el pedido.
            order_data = {
                "order_id": order_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pickup_zone": pickup_zone,
                "distance_km": distance_km,
                "priority": priority,
            }
            try:
                result = use_case.execute(order_data)
                _render_decision(result)
            except Exception as e:
                st.error(f"Error: {e}")

    with col2:
        st.subheader("🌊 Simular ráfaga")
        # Configuración de la ráfaga.
        burst_count = st.slider("Número de pedidos", 2, 20, 6)
        burst_zone = st.selectbox("Zona ráfaga", ["centro", "norte", "sur"], key="burst_zone")
        burst_priority = st.selectbox("Prioridad ráfaga", ["normal", "express"], key="burst_prio")

        if st.button("🚀 Simular ráfaga", type="secondary"):
            st.markdown(f"**Enviando {burst_count} pedidos a `{burst_zone}`...**")
            results = []
            # Enviar N pedidos seguidos a la misma zona.
            for i in range(burst_count):
                order_data = {
                    "order_id": f"burst_{i:03d}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "pickup_zone": burst_zone,
                    "distance_km": 2.0 + i * 0.5,
                    "priority": burst_priority,
                }
                try:
                    result = use_case.execute(order_data)
                    results.append(result)
                except Exception as e:
                    results.append({"order_id": f"burst_{i:03d}", "status": "ERROR", "error": str(e)})

            # Mostrar todos los resultados con emoji de status.
            for r in results:
                emoji = _status_color(r.get("status", "ERROR"))
                courier = r.get("assigned_courier", "—")
                st.markdown(f"{emoji} `{r['order_id']}` → **{r.get('status', 'ERROR')}** → {courier}")

    # ---- Snapshot del estado actual ----
    st.divider()
    st.subheader("📊 Estado actual")
    engine = use_case._engine  # noqa: SLF001
    snapshot = engine._state.snapshot()  # noqa: SLF001
    st.json(snapshot)


if __name__ == "__main__":
    # Cuando se ejecuta directamente, construir la app via composition root.
    from infrastructure.config import EngineConfig, build_rules
    from infrastructure.mock_pricing import MockPricing
    from infrastructure.system_clock import SystemClock
    from domain.engine import AssignmentEngine
    from domain.pricing import CircuitBreaker
    from domain.state import State
    from domain.surge import SurgeController

    # Cargar configuración desde env.
    config = EngineConfig.from_env()
    # Construir couriers desde session_state o defaults.
    couriers = [
        Courier(courier_id=c["courier_id"], zone=c["zone"],
                active_orders=c["active_orders"], max_capacity=c["max_capacity"])
        for c in st.session_state.get("couriers", [])
    ] or [
        Courier("cour_A", "centro", 1, 3),
        Courier("cour_B", "norte", 0, 3),
        Courier("cour_C", "centro", 3, 3),
    ]
    # Wiring de dependencias (DI).
    state = State(couriers)
    surge = SurgeController(config.surge)
    cb = CircuitBreaker(config.pricing)
    clock = SystemClock()
    pricing = MockPricing(config.pricing_failure_rate, seed=42)
    engine = AssignmentEngine(state, build_rules(config), surge, cb, config.pricing, clock, pricing)
    use_case = AssignOrderUseCase(engine)
    main(use_case)
