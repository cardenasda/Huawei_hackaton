# 🏛️ Documento de Arquitectura — FlowMatch Assignment Engine

> **Rol:** Arquitectura de Software
> **Principio rector:** Clean Architecture + Hexagonal (Ports & Adapters)
> **Objetivo:** Motor de asignación en tiempo real, testeable, thread-safe, extensible.

---

## 1. Decisions de Diseño (Architecture Decision Records)

### ADR-001 — Clean Architecture por capas
**Contexto:** El sistema tiene lógica de negocio compleja (reglas, ráfagas, circuit breaker) que debe ser testeable sin depender de HTTP, DB ni UI.

**Decisión:** Separar en 3 capas con regla de dependencia hacia adentro:
```
presentation/  →  application/  →  domain/
     (UI/API)      (use cases)     (pure logic)
         ↑              ↑              ↑
infrastructure/ ───────┘              │
   (adapters)                         │
     config, pricing, clock ──────────┘
```
- **domain/**: lógica pura, SIN dependencias externas (ni FastAPI, ni requests, ni datetime real)
- **application/**: orquesta casos de uso, define **ports** (interfaces)
- **infrastructure/**: adapters concretos (FastAPI, mock pricing, config loader)
- **presentation/**: UI (Streamlit)

**Consecuencia:** El dominio es 100% testeable con tests unitarios puros. La UI y API son intercambibles.

---

### ADR-002 — Strategy Pattern para reglas de asignación
**Contexto:** Las reglas (same_zone, capacity, least_loaded, min_cost) deben ser activables/desactivables y configurables independientemente.

**Decisión:** Cada regla implementa una interfaz común `AssignmentRule`:
```python
class AssignmentRule(ABC):
    @abstractmethod
    def apply(self, order: Order, candidates: list[Courier], state: State) -> list[Courier]: ...
    @abstractmethod
    def explain(self, order: Order, chosen: Courier, state: State) -> Reason: ...
```
- El `AssignmentEngine` es una **pipeline**: recibe candidatos, cada regla los filtra/ordena
- El orden de las reglas es configurable
- Reglas nuevas se añaden sin tocar el engine (Open/Closed)

---

### ADR-003 — Thread-safe State con locks granulares
**Contexto:** Bono B requiere concurrencia segura. El estado compartido (active_orders, cola, historial) debe ser seguro ante N hilos.

**Decisión:** `State` encapsula todo estado mutable detrás de un `threading.RLock`:
- `active_orders` por repartidor: lock por repartidor (granularidad fina)
- `queue` de espera: lock dedicado
- `surge_history`: lock dedicado
- Operaciones atómicas: `assign_to_courier()`, `enqueue()`, `dequeue()`

**Consecuencia:** No hay condiciones de carrera; sobre-asignación imposible por diseño.

---

### ADR-004 — Circuit Breaker como patrón de resiliencia
**Contexto:** El servicio de tarifa dinámica falla ~30%. Sin protección, degrada toda la asignación.

**Decisión:** Implementar Circuit Breaker con 3 estados (Closed/Open/Half-Open):
- **Closed:** llamadas normales, contador de fallos
- **Open:** tras N fallos consecutivos, bloquea por T segundos → fallback a tarifa fija
- **Half-Open:** tras T segundos, 1 llamada de prueba → recupera o vuelve a Open

---

### ADR-005 — Sliding Window (no ventana fija)
**Contexto:** Rate limiting por repartidor. Ventana fija permite ráfagas en los bordes.

**Decisión:** Sliding window con timestamps: mantener lista de eventos, purgar los >W segundos, contar los restantes. O(1) amortizado con purga periódica.

---

### ADR-006 — Dependency Injection para testabilidad
**Contexto:** Tests necesitan controlar el tiempo (expiración de contención, sliding window) y el pricing (forzar fallos).

**Decisión:** Inyectar `Clock` y `PricingService` como ports:
- `Clock` interface → `SystemClock` (prod) / `FakeClock` (tests)
- `PricingService` interface → `MockPricing` (prod/test)
- El engine NO instancia nada; recibe todo por constructor

---

### ADR-007 — Value Objects inmutables para Order y Decision
**Contexto:** Los pedidos y decisiones no deben mutarse accidentalmente.

**Decisión:** Usar `dataclass(frozen=True)` para `Order`, `Reason`. `Decision` es inmutable tras creación. `Courier` es mutable solo vía `State` (encapsulación).

---

## 2. Estructura de Carpetas

```
codigo/
├── domain/                         # 🧠 Lógica pura (0 dependencias externas)
│   ├── __init__.py
│   ├── models.py                   # Value objects: Order, Courier, Decision, Reason
│   ├── state.py                    # Estado compartido thread-safe
│   ├── rules/                      # Strategy pattern
│   │   ├── __init__.py
│   │   ├── base.py                 # AssignmentRule (ABC)
│   │   ├── same_zone.py            # Fase 1: misma zona
│   │   ├── capacity.py             # Fase 1: capacidad
│   │   ├── least_loaded.py         # Fase 1: menor carga
│   │   └── min_cost.py             # Fase 3: menor costo
│   ├── surge.py                    # Fase 2: sliding window + contención
│   ├── pricing.py                  # Fase 3: circuit breaker
│   └── engine.py                   # Orquestador: pipeline de reglas
│
├── application/                    # ⚙️ Casos de uso + ports
│   ├── __init__.py
│   ├── assign_service.py           # Caso de uso: asignar pedido
│   └── ports/                      # Interfaces (abstracciones)
│       ├── __init__.py
│       ├── clock.py                # Clock interface (testabilidad tiempo)
│       └── pricing.py              # PricingService interface
│
├── infrastructure/                 # 🔌 Adapters concretos
│   ├── __init__.py
│   ├── config.py                   # Carga config (env + defaults)
│   ├── mock_pricing.py             # MockPricing (30% fallo)
│   ├── system_clock.py             # SystemClock (tiempo real)
│   └── api/                        # Adapter HTTP (FastAPI)
│       ├── __init__.py
│       └── main.py                 # POST /assign, GET /state
│
├── presentation/                   # 🖥️ UI
│   ├── __init__.py
│   └── streamlit_app.py            # Fase 4: formulario + ráfaga
│
├── tests/                          # 🧪 Suite de pruebas
│   ├── __init__.py
│   ├── conftest.py                 # Fixtures compartidas
│   ├── test_fase1_assign.py        # Tests Fase 1
│   ├── test_fase2_surge.py         # Tests Fase 2
│   ├── test_fase3_pricing.py       # Tests Fase 3
│   ├── test_edge_cases.py          # Casos borde
│   └── test_concurrency.py         # Bono B
│
├── config/
│   └── settings.yaml               # Configuración por defecto
├── main.py                         # Entry point (CLI / lanzar API)
└── __init__.py
```

---

## 3. Flujo de una asignación (sequence)

```
Cliente (UI/API)
    │
    ▼
application/assign_service.py   ← AssignOrderUseCase
    │
    ├─► domain/state.py         ← Lee estado repartidores (thread-safe)
    │
    ├─► domain/surge.py         ← ¿Contención activa? (sliding window)
    │       │
    │       ├─► REJECTED (si normal + contención activa)
    │       └─► continúa (si express o sin contención)
    │
    ├─► domain/engine.py        ← Pipeline de reglas
    │       │
    │       ├─► rules/same_zone.py     → filtra candidatos
    │       ├─► rules/capacity.py      → filtra llenos
    │       ├─► rules/least_loaded.py  → ordena por carga
    │       └─► rules/min_cost.py      → ordena por costo (Fase 3)
    │
    ├─► domain/pricing.py       ← Circuit breaker + tarifa
    │       │
    │       └─► ports/pricing.py → MockPricing (30% fallo)
    │
    ├─► domain/state.py         ← Actualiza estado (atomic)
    │
    └─► domain/models.py        → Decision (inmutable)
                │
                ▼
        Respuesta al cliente
```

---

## 4. Patrones aplicados

| Patrón | Dónde | Por qué |
|---|---|---|
| **Clean Architecture** | Capas domain/app/infra | Testabilidad + separación |
| **Strategy** | `rules/` | Reglas activables y ordenables |
| **Pipeline** | `engine.py` | Reglas se encadenan |
| **Circuit Breaker** | `pricing.py` | Resiliencia ante fallos |
| **Sliding Window** | `surge.py` | Rate limiting sin bordes |
| **Dependency Injection** | `assign_service.py` | Testabilidad (clock, pricing) |
| **Value Object** | `models.py` | Inmutabilidad de Order/Decision |
| **Thread-safe State** | `state.py` | Concurrencia segura (Bono B) |
| **Port/Adapter** | `application/ports/` | Desacoplar infraestructura |

---

## 5. Garantías de la arquitectura

- ✅ **Nunca sobre-asigna:** `State.assign_to_courier()` es atómica y valida capacidad
- ✅ **Explicable:** Cada regla produce un `Reason` trazable
- ✅ **Configurable:** Reglas y parámetros via `settings.yaml` + env vars
- ✅ **Testeable:** `FakeClock` + `FakePricing` permiten tests deterministas
- ✅ **Thread-safe:** Locks granulares en `State`
- ✅ **Extensible:** Nueva regla = nuevo archivo en `rules/`, sin tocar engine
- ✅ **Resiliente:** Circuit breaker degrada a tarifa fija sin fallar
