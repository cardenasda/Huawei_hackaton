# 📋 Tareas de Desarrollo — Reto 2: FlowMatch Assignment Engine

> **Objetivo:** Construir un motor de asignación en tiempo real que decida a qué repartidor asignar cada pedido, respetando límites y prioridades, con explicabilidad, control de ráfagas, optimización de costo e interfaz gráfica.
>
> **Modelo IA copiloto:** GLM 5.2 (MaaS)
> **Stack propuesto:** Python 3.10+ · FastAPI (API) · Streamlit (UI Fase 4) · pytest (tests)
> **Tiempo total estimado:** 80 minutos

---

## 🧾 Rúbrica de evaluación (referencia rápida)

| Categoría | Pts | Criterio |
|---|---|---|
| Funcionalidad core | 10 | Fase 1: asignación base + prioridad + capacidad configurable |
| Funcionalidad core | 10 | Fase 2: ráfagas ventana deslizante + contención auto-expiración |
| Funcionalidad core | 10 | Fase 3: optimización costo + circuit breaker degradación segura |
| Funcionalidad core | 8 | Clasificación ASSIGNED/QUEUED/REJECTED correcta |
| Calidad técnica | 11 | Arquitectura modular, separación de responsabilidades |
| Calidad técnica | 9 | Manejo de errores y casos borde |
| Explicabilidad | 14 | Razones claras y trazables a reglas específicas |
| Interfaz gráfica | 8 | Formulario + muestra estado/repartidor/costo/razones |
| Interfaz gráfica | 5 | Simular ráfaga + visualizar contención en vivo |
| Uso efectivo de IA | 10 | Bitácora de prompts con iteración y pensamiento crítico |
| Uso efectivo de IA | 5 | Evidencia de entendimiento del código generado |
| **Subtotal base** | **100** | |
| Bonos A/B/C/D | +30 | Lotes / concurrencia / soporte exportable / escenarios extremos |

---

## 🏗️ Fase 0 — Setup y arquitectura base

> **Cubre rúbrica:** Calidad técnica (11 pts) — arquitectura modular

### Tarea 0.1 — Definir estructura de carpetas del proyecto
- [ ] Crear estructura modular bajo `daniel-cardenas-g1/codigo/`:
  ```
  codigo/
  ├── config/           # Configuración de reglas y parámetros
  │   └── settings.py   # Reglas activables/desactivables
  ├── engine/           # Núcleo del motor de asignación
  │   ├── models.py     # Dataclasses: Order, Courier, Decision, Reason
  │   ├── assigner.py   # Lógica de asignación (Fase 1)
  │   ├── surge.py      # Control de ráfagas (Fase 2)
  │   ├── pricing.py    # Tarifa + circuit breaker (Fase 3)
  │   └── state.py      # Estado compartido (carga, cola, historial)
  ├── api/              # Endpoint FastAPI
  │   └── main.py       # POST /assign
  ├── ui/               # Interfaz Streamlit (Fase 4)
  │   └── app.py
  └── tests/            # Suite de pruebas pytest
  ```
- **Criterio de aceptación:** Separación clara de responsabilidades; cada módulo tiene un único propósito.

### Tarea 0.2 — Definir modelos de datos (`models.py`)
- [ ] Implementar dataclasses/Pydantic para: `Order`, `Courier`, `Decision`, `Reason`, `PricingStatus`
- [ ] Campo `reasons[]` como lista de objetos `{rule, detail}` desde el inicio
- **Cubre rúbrica:** Explicabilidad (14 pts) — formato de salida trazable

### Tarea 0.3 — Sistema de configuración de reglas (`settings.py`)
- [ ] Cada regla (same_zone, capacity, least_loaded, surge, pricing) debe poder **activarse/desactivarse** y ajustar sus parámetros
- [ ] Cargar desde archivo config o variables de entorno
- **Cubre rúbrica:** Funcionalidad core Fase 1 (10 pts) — "configurable"

---

## ⚡ Fase 1 — Asignación base por prioridad

> **Cubre rúbrica:** Funcionalidad core Fase 1 (10 pts) + Clasificación estado (8 pts) + Explicabilidad (14 pts)

### Tarea 1.1 — Implementar regla "misma zona primero"
- [ ] Filtrar repartidores cuyo `zone == order.pickup_zone` como candidatos preferentes
- [ ] Generar `reason`: `{rule: "same_zone_preferred", detail: "cour_X is in pickup_zone=Y"}`
- **Verificación:** Con el ejemplo del enunciado, `cour_A` y `cour_C` son candidatos por zona `centro`

### Tarea 1.2 — Implementar regla "respetar capacidad"
- [ ] Descartar repartidores con `active_orders >= max_capacity`
- [ ] Si todos están llenos → estado `QUEUED`, `assigned_courier: null`, razón `all_couriers_at_capacity`
- [ ] Generar `reason`: `{rule: "capacity_ok", detail: "cour_A at 1/3 (cour_C skipped: 3/3 full)"}`
- **Verificación:** `cour_C` (3/3) se descarta; si todos llenos → `QUEUED`

### Tarea 1.3 — Implementar regla "menor carga primero"
- [ ] Entre candidatos válidos, elegir el de menor `active_orders`
- [ ] Generar `reason`: `{rule: "least_loaded", detail: "cour_A chosen (1 active order, lowest among valid)"}`
- **Verificación:** `cour_A` (1 pedido) gana sobre otros con más carga

### Tarea 1.4 — Actualizar estado del repartidor asignado
- [ ] Al asignar, incrementar `active_orders` del repartidor en +1 (persistencia en memoria)
- [ ] Mantener cola de espera (`QUEUED`) con los pedidos pendientes
- **Cubre rúbrica:** Clasificación estado (8 pts)

### Tarea 1.5 — Función `assign(order)` integrada
- [ ] Orquestar las 3 reglas en orden de prioridad
- [ ] Retornar objeto `Decision` con `order_id`, `status`, `assigned_courier`, `reasons[]`
- [ ] **Prueba con ejemplo del enunciado** debe dar: `ASSIGNED → cour_A` con las 3 razones exactas
- **Criterio de aceptación:** Salida idéntica al ejemplo de Fase 1 del enunciado

---

## 🌊 Fase 2 — Control de ráfagas (ventanas deslizantes)

> **Cubre rúbrica:** Funcionalidad core Fase 2 (10 pts) + Clasificación estado (8 pts)

### Tarea 2.1 — Límite de ritmo por repartidor (sliding window)
- [ ] Implementar ventana deslizante (no ventana fija): un repartidor no recibe >N pedidos nuevos en W segundos
- [ ] Parámetros configurables (ej: máx 3 pedidos en 10s)
- [ ] Registrar timestamp de cada asignación por repartidor
- **Verificación:** Un repartidor con capacidad libre pero saturado por ritmo → se salta

### Tarea 2.2 — Balanceo de zona
- [ ] Si una `pickup_zone` recibe avalancha de pedidos, repartir entre repartidores de zonas vecinas
- [ ] Definir mapa de zonas vecinas configurable
- **Verificación:** Bajo ráfaga en `centro`, se asigna a repartidores de zonas vecinas antes que sobrecargar `centro`

### Tarea 2.3 — Modo de contención por saturación sostenida
- [ ] Detectar: ventana deslizante de 3 pedidos consecutivos donde TODOS los repartidores están al tope Y la cola crece
- [ ] Activar modo contención temporal: rechazar pedidos `normal` → `REJECTED` por 120s (configurable)
- [ ] Pedidos `express` siguen intentando encolarse (`QUEUED`)
- [ ] Generar razón: `{rule: "surge_protection_active", detail: "all couriers full, queue growing for 3 orders (window=120s)"}`
- **Verificación:** Pedido #6 normal → `REJECTED` con razón exacta del enunciado

### Tarea 2.4 — Expiración automática de contención
- [ ] Tras 120s, desactivar contención automáticamente
- [ ] Pedidos `normal` subsecuentes dentro de la ventana traen razón `surge_window_active` sin recorrer repartidores
- [ ] Tras expirar, volver a evaluar normalmente
- **Criterio de aceptación:** Salida del pedido #6 y #7 coincide con los ejemplos del enunciado

---

## 💰 Fase 3 — Optimización de costo + resiliencia

> **Cubre rúbrica:** Funcionalidad core Fase 3 (10 pts) + Explicabilidad (14 pts)

### Tarea 3.1 — Selección por menor costo
- [ ] Cuando hay varios repartidores válidos, elegir el que minimiza costo del envío (menor `distance_km`)
- [ ] Calcular costo en COP (ej: tarifa base + por km)
- [ ] Añadir campo `cost` al objeto `Decision`
- **Verificación:** Entre 2 repartidores válidos, se elige el de menor distancia/costo

### Tarea 3.2 — Mock del servicio de tarifa dinámica (`mock_pricing()`)
- [ ] Simular llamada externa con 30% probabilidad de fallo o timeout (>2s)
- [ ] Retornar tarifa dinámica cuando funciona
- **Verificación:** En múltiples llamadas, ~30% fallan o demoran

### Tarea 3.3 — Circuit breaker
- [ ] **Closed:** funcionamiento normal
- [ ] Si 3 fallos seguidos → **Open**: dejar de llamar por 15s, usar tarifa base fija (degradación segura)
- [ ] Tras 15s → **Half-open**: una sola llamada de prueba
  - Si éxito → **Closed**
  - Si fallo → **Open** de nuevo
- [ ] Añadir campo `pricing_status` al `Decision`: `ok` / `circuit_open_degraded_flat_rate` / `circuit_half_open`
- **Criterio de aceptación:** Salida de Fase 3 coincide con ejemplo del enunciado (incluye `cost` y `pricing_status`)

### Tarea 3.4 — Desglose completo de la decisión
- [ ] Cada respuesta incluye: repartidor elegido (o por qué no), reglas activadas, costo resultante
- **Cubre rúbrica:** Explicabilidad (14 pts)

---

## 🖥️ Fase 4 — Interfaz gráfica de verificación

> **Cubre rúbrica:** Interfaz gráfica (8 + 5 = 13 pts)

### Tarea 4.1 — Formulario de ingreso de pedido (Streamlit)
- [ ] Campos: `pickup_zone`, `distance_km`, `priority` (select normal/express), `order_id`, `timestamp`
- [ ] Editor de estado de repartidores (precargado, editable)
- [ ] Botón "Asignar" que envía el pedido al motor
- **Cubre rúbrica:** Interfaz (8 pts) — formulario sin curl/Postman

### Tarea 4.2 — Visualización clara de la decisión
- [ ] Mostrar estado con color: 🟢 `ASSIGNED` / 🟡 `QUEUED` / 🔴 `REJECTED`
- [ ] Mostrar repartidor asignado, costo y desglose de reglas
- **Cubre rúbrica:** Interfaz (8 pts)

### Tarea 4.3 — Botón "Simular ráfaga (Nx)"
- [ ] Botón que dispara N pedidos seguidos a la misma zona (ej: 6x rápido)
- [ ] Mostrar en vivo cómo los primeros se asignan, repartidores se llenan, y el 6º sale `REJECTED` (rojo)
- [ ] Visualizar activación de contención por saturación en tiempo real
- **Criterio de aceptación:** El jurado ve la contención en vivo sin mirar logs
- **Cubre rúbrica:** Interfaz (5 pts)

---

## 🛡️ Calidad técnica — Manejo de errores y casos borde

> **Cubre rúbrica:** Calidad técnica (9 pts)

### Tarea 5.1 — Validación de entradas
- [ ] Pedido sin repartidores (`couriers: []`) → `REJECTED` con razón clara
- [ ] `distance_km` negativa → error validación
- [ ] `priority` inválida (no `normal`/`express`) → error validación
- [ ] `timestamp` futuro o malformado → error validación
- [ ] `max_capacity` <= 0 → error validación

### Tarea 5.2 — Robustez del motor
- [ ] Estado nunca se corrompe ante entradas inválidas
- [ ] Logs informativos para depuración
- [ ] Mensajes de error user-friendly en la UI

---

## 🧪 Pruebas automatizadas

> **Cubre rúbrica:** Calidad técnica (9 pts) + soporta Bono D (6 pts)

### Tarea 6.1 — Tests de Fase 1
- [ ] Test ejemplo del enunciado → `ASSIGNED cour_A`
- [ ] Test todos llenos → `QUEUED`
- [ ] Test sin repartidores → `REJECTED`
- [ ] Test reglas desactivables

### Tarea 6.2 — Tests de Fase 2
- [ ] Test ráfaga de 6 pedidos → pedido #6 `REJECTED`
- [ ] Test pedido `express` durante contención → `QUEUED`
- [ ] Test expiración de contención tras 120s

### Tarea 6.3 — Tests de Fase 3
- [ ] Test circuit breaker abre tras 3 fallos
- [ ] Test degradación a tarifa base
- [ ] Test half-open → recovery

---

## 🤖 Uso efectivo de IA — Bitácora de prompts

> **Cubre rúbrica:** Uso efectivo de IA (10 + 5 = 15 pts)

### Tarea 7.1 — Documentar prompts en `prompt_usado.txt`
- [ ] Registrar cada prompt clave usado con GLM 5.2
- [ ] Documentar iteración: prompt inicial → respuesta → ajuste → resultado final
- [ ] No copy-paste ciego: mostrar pensamiento crítico y refinamiento
- **Criterio de aceptación:** Bitácora muestra evolución, no un solo prompt mágico

### Tarea 7.2 — Evidencia de entendimiento del código
- [ ] Comentarios explicando decisiones de diseño no triviales
- [ ] Poder explicar cualquier parte del código generado
- [ ] README documenta arquitectura y decisiones

---

## 📦 Entregables finales

> **Cubre rúbrica:** Todos los criterios indirectamente

### Tarea 8.1 — README actualizado
- [ ] Arquitectura elegida y justificación
- [ ] Decisiones de diseño
- [ ] Cómo correr el proyecto (instalación + ejecución API y UI)
- [ ] Qué bonos se implementaron

### Tarea 8.2 — `requerimientos.txt` completo
- [ ] Listar todas las dependencias con versiones: fastapi, uvicorn, streamlit, pydantic, pytest, etc.

### Tarea 8.3 — Verificación end-to-end
- [ ] Ejecutar API + UI desde cero siguiendo el README
- [ ] Reproducir el flujo completo del enunciado (Fase 1 → ráfaga → contención → costo)

---

## 💎 Bonos (elegir estratégicamente 1-2)

> **Recomendación:** Bono D (escenarios extremos, +6) + Bono B (concurrencia, +8) dan mejor ROI

### Tarea BONUS A — Optimización global por lotes (+10 pts)
- [ ] Agrupar pedidos en ventana corta y resolver asignación conjunta óptima (emparejamiento)
- [ ] Demostrar caso donde supera al greedy

### Tarea BONUS B — Concurrencia segura (+8 pts)
- [ ] Prueba de carga real con N hilos asignando simultáneamente
- [ ] Locks/atomic en `active_orders` y cola de espera
- [ ] Demostrar: no sobre-asignación, conteo correcto

### Tarea BONUS C — Explicabilidad exportable (+6 pts)
- [ ] Para cada `REJECTED`, generar reporte JSON para soporte
- [ ] Incluir: reglas, estado repartidores, timestamp, explicación en lenguaje natural (IA)

### Tarea BONUS D — Suite escenarios extremos (+6 pts)
- [ ] Ráfaga a una sola zona
- [ ] Todos los repartidores llenos de golpe
- [ ] Avalancha de pedidos `express`
- [ ] Pedido justo cuando expira contención
- [ ] Verificar: nunca sobre-asigna por encima de capacidad

---

## 📊 Resumen de cobertura de rúbrica

| Tareas | Categoría rúbrica | Pts cubiertos |
|---|---|---|
| 0.1–0.3, 1.1–1.5 | Funcionalidad core Fase 1 | 10 |
| 2.1–2.4 | Funcionalidad core Fase 2 | 10 |
| 3.1–3.4 | Funcionalidad core Fase 3 | 10 |
| 1.4, 2.3, 2.4 | Clasificación estado | 8 |
| 0.1, 0.3 | Arquitectura modular | 11 |
| 5.1–5.2, 6.1–6.3 | Errores y casos borde | 9 |
| 0.2, 1.1–1.3, 3.4 | Explicabilidad | 14 |
| 4.1–4.2 | Interfaz formulario | 8 |
| 4.3 | Interfaz ráfaga | 5 |
| 7.1 | Bitácora prompts | 10 |
| 7.2 | Entendimiento código | 5 |
| BONUS A–D | Bonos | +30 |
| **Total** | | **100 + 30** |
