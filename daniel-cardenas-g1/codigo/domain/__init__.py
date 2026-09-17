"""Domain layer — Lógica de negocio pura, sin dependencias externas.

Esta capa contiene las reglas de negocio del motor FlowMatch:
- models.py: Value Objects (Order, Courier, Decision, Reason)
- state.py: Estado compartido thread-safe
- engine.py: Orquestador de reglas (pipeline)
- surge.py: Control de ráfagas (sliding window + contención)
- pricing.py: Circuit breaker + cálculo de costo
- rules/: Strategy pattern para reglas de asignación
"""
