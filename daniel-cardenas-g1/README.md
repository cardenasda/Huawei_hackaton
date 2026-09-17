# Reto de Programación - Huawei Hackathon

## Datos del participante

- **Nombre:** Daniel Cardenas
- **Grupo:** 1
- **Rama:** `daniel-cardenas-g1`

## Descripción

**FlowMatch Assignment Engine** — Motor de asignación de pedidos a repartidores
en tiempo real para la app de domicilios QuickBite. Construido con Clean Architecture
+ Hexagonal (Ports & Adapters) usando GLM-5.2 como copiloto de desarrollo.

### Arquitectura

```
codigo/
├── domain/          # Lógica pura (models, state thread-safe, rules, surge, pricing, engine)
├── application/     # Use cases + ports (Clock, PricingService)
├── infrastructure/  # Adapters (config, mock_pricing, FastAPI)
├── presentation/    # UI Streamlit (Fase 4)
├── tests/           # 29 tests (Fase 1, 2, 3 + edge cases)
└── main.py          # Composition Root (DI wiring)
```

**Patrones aplicados:** Clean Architecture, Strategy, Pipeline, Circuit Breaker,
Sliding Window, Dependency Injection, Value Objects, Thread-safe State.

### Fases implementadas

| Fase | Descripción | Estado |
|---|---|---|
| 0 | Arquitectura + 7 ADRs | ✅ |
| 1 | Asignación base + prioridad + capacidad | ✅ |
| 2 | Sliding window + contención auto-expirable | ✅ |
| 3 | Optimización costo + circuit breaker | ✅ |
| 4 | Interfaz Streamlit (formulario + ráfaga) | ✅ |
| Edge | Casos borde + no sobre-asignación | ✅ |

## Estructura del proyecto

```
📂 daniel-cardenas-g1/
├── 📄 README.md              # Este archivo
├── 📄 requerimientos.txt     # Dependencias
├── 📄 prompt_usado.txt       # Bitácora de prompts (GLM-5.2)
├── 📄 TAREAS_RETO_2.md       # Plan de tareas mapeado a rúbrica
└── 📂 codigo/                # Código fuente (Clean Architecture)
```

## Requisitos previos

- Python 3.10 o superior
- pip (gestor de paquetes de Python)
- Git

## Instalación

1. Clonar el repositorio:

   ```bash
   git clone https://github.com/huawei-cloud-colombia/Huawei_hackaton.git
   cd Huawei_hackaton
   ```

2. Cambiar a la rama del proyecto:

   ```bash
   git checkout daniel-cardenas-g1
   ```

3. Crear y activar un entorno virtual (recomendado):

   ```bash
   python -m venv venv
   # En Windows
   venv\Scripts\activate
   # En Linux/Mac
   source venv/bin/activate
   ```

4. Instalar las dependencias:

   ```bash
   pip install -r daniel-cardenas-g1/requerimientos.txt
   ```

## Ejecución

Desde la carpeta `daniel-cardenas-g1/codigo/`:

### Demo del enunciado (Fase 1)
```bash
python main.py demo
```

### API REST (FastAPI)
```bash
python main.py api
# POST http://localhost:8000/assign
# GET  http://localhost:8000/state
```

### Interfaz gráfica (Streamlit - Fase 4)
```bash
streamlit run presentation/streamlit_app.py
```

### Tests
```bash
python -m pytest tests/ -v
# 29/29 tests passing
```

## Decisiones de diseño

- **Clean Architecture:** El dominio no depende de FastAPI ni requests → 100% testeable.
- **Strategy Pattern:** Reglas activables/desactivables y ordenables vía config.
- **Circuit Breaker:** Degradación segura a tarifa fija cuando el pricing falla.
- **Sliding Window:** Rate limiting real (no ventana fija) sin ráfagas en bordes.
- **Thread-safe State:** Locks granulares por courier → no sobre-asignación.
- **Dependency Injection:** FakeClock + FakePricing para tests deterministas.

## Prompts utilizados

La bitácora de prompts usados con GLM-5.2 está en `prompt_usado.txt`.
Documenta 7 prompts con iteración, pensamiento crítico y bugs encontrados.

## Autor

Daniel Cardenas - Grupo 4
