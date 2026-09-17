"""Motor de asignación — orquesta el pipeline de reglas.

El engine es el caso de uso principal: recibe un pedido, ejecuta las reglas
configuradas como pipeline, aplica control de surge, computa pricing, y retorna
una Decision inmutable.

Decisiones de diseño:
- Las reglas se inyectan (lista de AssignmentRule) → el orden es configurable.
- SurgeController y CircuitBreaker se inyectan.
- Clock se inyecta (port) para tests deterministas.
- State se inyecta (compartido, thread-safe).

Flujo:
1. Check contención activa → REJECT normal / QUEUE express.
2. Pipeline de reglas (same_zone → capacity → least_loaded → min_cost).
3. Zone balancing si no hay same-zone candidates.
4. Rate limiting por courier (sliding window).
5. Si no hay candidatos → registrar full event (puede activar contención) → QUEUE/REJECT.
6. Computar costo via circuit breaker.
7. Asignar atómicamente (thread-safe).
"""

from __future__ import annotations

from datetime import datetime

from .models import Courier, Decision, Order, OrderStatus, Reason
from .pricing import CircuitBreaker, PricingConfig, PricingStatus, compute_cost
from .rules.base import AssignmentRule
from .state import State
from .surge import SurgeController


class AssignmentEngine:
    """Motor principal que asigna pedidos a couriers.

    Thread-safe: delega mutaciones de estado a State (que es thread-safe).
    """

    def __init__(
        self,
        state: State,
        rules: list[AssignmentRule],
        surge: SurgeController,
        circuit_breaker: CircuitBreaker,
        pricing_config: PricingConfig,
        clock,  # Clock port (application.ports.clock.Clock)
        pricing_service,  # PricingService port (application.ports.pricing.PricingService)
    ) -> None:
        """Inicializa el engine con todas las dependencias inyectadas.

        Args:
            state: Estado compartido thread-safe.
            rules: Lista de reglas en orden de ejecución (pipeline).
            surge: Controlador de surge (rate limiting + contención).
            circuit_breaker: Circuit breaker para el servicio de pricing.
            pricing_config: Configuración de pricing.
            clock: Port de reloj (para testabilidad).
            pricing_service: Port de servicio de tarifa dinámica.
        """
        self._state = state
        self._rules = rules
        self._surge = surge
        self._cb = circuit_breaker
        self._pricing_config = pricing_config
        self._clock = clock
        self._pricing_service = pricing_service

    def assign(self, order: Order) -> Decision:
        """Procesa un pedido y retorna una decisión.

        Este es el entry point principal. Ejecuta el flujo completo:
        1. Check contención activa → REJECT normal / QUEUE express.
        2. Pipeline de reglas (same_zone → capacity → least_loaded → min_cost).
        3. Zone balancing si no hay same-zone candidates.
        4. Rate limiting por courier (sliding window).
        5. Si no hay candidatos → registrar full event → QUEUE/REJECT.
        6. Computar costo via circuit breaker.
        7. Asignar atómicamente (thread-safe).

        Args:
            order: El pedido a procesar (ya validado).

        Returns:
            Decision inmutable con el resultado.
        """
        now = self._clock.now()
        reasons: list[Reason] = []

        # --- 1. Check si la contención YA está activa ---
        containment = self._surge.check_active_containment(order, now)
        if containment.should_reject:
            # Contención activa + pedido normal → REJECTED inmediatamente.
            reasons.append(containment.reason)
            return Decision(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                assigned_courier=None,
                reasons=reasons,
            )
        if containment.should_queue:
            # Contención activa + pedido express → QUEUED.
            reasons.append(containment.reason)
            self._state.enqueue(order, now)
            return Decision(
                order_id=order.order_id,
                status=OrderStatus.QUEUED,
                assigned_courier=None,
                reasons=reasons,
            )

        # --- 2. Ejecutar pipeline de reglas ---
        couriers = self._state.get_couriers()
        candidates = list(couriers)
        for rule in self._rules:
            result = rule.apply(order, candidates, self._state)
            candidates = result.candidates
            if result.reason:
                reasons.append(result.reason)
            if not candidates:
                break  # No hay candidatos, salir del pipeline.

        # --- 3. Zone balancing: si no hay candidatos, probar zonas vecinas ---
        if not candidates:
            neighbors = self._surge.get_neighbor_zones(order.pickup_zone)
            neighbor_couriers = [
                c for c in couriers
                if c.zone in neighbors and c.is_available
            ]
            if neighbor_couriers:
                # Ordenar por menor carga (least loaded first).
                neighbor_couriers.sort(key=lambda c: c.active_orders)
                candidates = neighbor_couriers
                reasons.append(Reason(
                    rule="zone_balancing",
                    detail=f"no couriers in {order.pickup_zone}, using neighbors: {[c.courier_id for c in candidates]}",
                ))

        # --- 4. Aplicar rate limiting por courier (sliding window) ---
        if candidates:
            # Filtrar couriers que no están rate-limited.
            rate_limited = [
                c for c in candidates
                if not self._surge.is_courier_rate_limited(c.courier_id, self._state, now)
            ]
            if len(rate_limited) < len(candidates):
                # Algunos couriers fueron saltados por rate limiting.
                skipped = [c.courier_id for c in candidates if c not in rate_limited]
                reasons.append(Reason(
                    rule="courier_rate_limited",
                    detail=f"skipped {skipped} (rate limit window)",
                ))
            candidates = rate_limited

        # --- 5. Si no hay candidatos → registrar full event (puede activar contención) ---
        if not candidates:
            full_event = self._surge.record_full_event(order, now)
            if full_event.should_reject:
                # Contención recién activada → REJECTED.
                reasons.append(full_event.reason)
                return Decision(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    assigned_courier=None,
                    reasons=reasons,
                )
            if full_event.reason:
                # Contención activada pero es express → QUEUED.
                reasons.append(full_event.reason)
            else:
                # Aún no se alcanza el threshold → encolar normalmente.
                reasons.append(Reason(
                    rule="all_couriers_at_capacity",
                    detail="no courier with free capacity available",
                ))
            self._state.enqueue(order, now)
            return Decision(
                order_id=order.order_id,
                status=OrderStatus.QUEUED,
                assigned_courier=None,
                reasons=reasons,
            )

        # --- 6. Seleccionar mejor candidato (primero después del pipeline) ---
        chosen = candidates[0]

        # --- 7. Computar costo via circuit breaker ---
        cost, pricing_status = self._compute_cost(order, now)

        # --- 8. Asignar atómicamente ---
        assigned = self._state.assign_to_courier(chosen.courier_id)
        if not assigned:
            # Race condition: el courier se llenó entre el check y la asignación.
            # Fallback: encolar el pedido.
            reasons.append(Reason(
                rule="race_condition_fallback",
                detail=f"{chosen.courier_id} became full during assignment; order queued",
            ))
            self._state.enqueue(order, now)
            return Decision(
                order_id=order.order_id,
                status=OrderStatus.QUEUED,
                assigned_courier=None,
                reasons=reasons,
                cost=cost,
                pricing_status=pricing_status,
            )

        # Registrar asignación para rate limiting + resetear contador de full.
        self._state.record_assignment(now, chosen.courier_id)
        self._surge.reset_full_counter()

        return Decision(
            order_id=order.order_id,
            status=OrderStatus.ASSIGNED,
            assigned_courier=chosen.courier_id,
            reasons=reasons,
            cost=cost,
            pricing_status=pricing_status,
        )

    def _compute_cost(
        self, order: Order, now: datetime
    ) -> tuple[float, PricingStatus]:
        """Computa el costo usando circuit breaker + servicio de pricing.

        Si el circuit breaker permite la llamada, intenta obtener el precio dinámico.
        Si falla, registra el fallo (puede abrir el circuito).
        Si el circuito está abierto, usa la tarifa base fija (degradación segura).

        Args:
            order: El pedido a cotizar.
            now: Tiempo actual.

        Returns:
            Tupla (costo_en_COP, estado_del_circuit_breaker).
        """
        if self._cb.allow_call(now):
            try:
                # Intentar obtener precio dinámico del servicio.
                dynamic_price = self._pricing_service.get_price(order, now)
                self._cb.record_success()
                status = self._cb.get_status()
                cost = compute_cost(
                    order.distance_km, self._pricing_config, status, dynamic_price
                )
                return cost, status
            except Exception:
                # El servicio falló → registrar fallo (puede abrir circuito).
                self._cb.record_failure(now)
        # Fallback: circuito abierto o servicio falló → tarifa degradada.
        status = self._cb.get_status()
        cost = compute_cost(order.distance_km, self._pricing_config, status)
        return cost, status
