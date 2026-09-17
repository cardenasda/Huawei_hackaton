"""Reglas de asignación — Strategy pattern.

Cada regla es una estrategia independiente y testeable que filtra/ordena candidatos.
El engine las encadena como pipeline. Nuevas reglas se añaden sin tocar el engine
(Open/Closed Principle).
"""
