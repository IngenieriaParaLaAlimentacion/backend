# Línea base de la prueba de carga

Informe de la corrida del 2026-10-29, la primera completa. Lo escribió el job `report` del workflow *Load tests* y se corrigió a mano después de revisarlo contra los artifacts:

- Decía que `checks` no aparecía en los JSON: sí aparece, y todos pasaron (sección 4).
- Decía que los escalones corrían seguidos: ya había 5 s de separación entre uno y otro (sección 8).
- Se agregó la hipótesis del proceso único de uvicorn (sección 6).

El job `report` recibe este archivo en cada corrida y compara los resultados nuevos contra él. Reemplazalo cuando una corrida nueva pase a ser la referencia.

---

# Informe de la prueba de carga

Corrida finalizada el 2026-10-29 (`run.json`). Código de los load tests: `dddc43d`. Commit desplegado: no informado (`target_revision: null`). Flujos ejecutados: `smoke`, `food_intake_sync`, `listings`, `measurement_sync`, `subject_sync`, `survey_response_sync`. Flujos fallidos: ninguno.

## 1. Resumen

- Se midió la API con escalones de 5, 10, 25 y 50 usuarios virtuales (VUs), de 120 s cada uno, sin pausa entre pedidos. Se probaron un listado y cuatro flujos de sincronización con escrituras idempotentes.
- No hubo errores en ningún flujo y ningún escalón (0,0 %). Todos los reenvíos (replays) devolvieron `200` (100 %). El `smoke` pasó sus 4 controles.
- El rendimiento deja de crecer entre 25 y 50 VUs en `food_intake_sync` (72,0 → 65,6 req/s) y `survey_response_sync` (34,0 → 41,3 req/s, con un máximo previo de 37,1 a 10 VUs). En el resto sigue creciendo, pero la latencia p95 se duplica o más.
- `survey_response_sync` es el flujo más costoso: con 25 VUs el p95 es 2,54 s y el p99 6,76 s; con 50 VUs el p99 llega a 9,83 s. A partir de 10 VUs no mejora su rendimiento, aunque sin errores.
- Con estos datos, 10 VUs es el último nivel con latencias aceptables en todos los flujos (p95 ≤ 641 ms). A 25 VUs ya hay degradación clara en `survey_response_sync`.
- No hay métricas de CPU, memoria ni conexiones a la base, así que las causas son hipótesis.

## 2. Resultados por flujo

Cada escalón dura 120 s (`profile.step_seconds`).

### smoke

Los 4 controles pasaron (backend listo, login, listado responde, listado con datos sembrados). No hay tabla por escalón.

### listings

| VUs | req/s | p50 | p95 | p99 | errores |
|---|---|---|---|---|---|
| 5 | 35,8 | 138 ms | 165 ms | 272 ms | 0,0 % |
| 10 | 63,1 | 147 ms | 234 ms | 460 ms | 0,0 % |
| 25 | 75,1 | 297 ms | 597 ms | 778 ms | 0,0 % |
| 50 | 93,1 | 494 ms | 1,01 s | 1,35 s | 0,0 % |

El rendimiento crece en todos los escalones, pero cada vez menos por VU: de 10 a 25 VUs sube solo de 63,1 a 75,1 req/s mientras el p50 se duplica (147 → 297 ms). Es el comienzo de la saturación. Sin errores.

### subject_sync

| VUs | req/s | p50 | p95 | p99 | errores | replays → 200 |
|---|---|---|---|---|---|---|
| 5 | 31,0 | 146 ms | 268 ms | 513 ms | 0,0 % | 100,0 % |
| 10 | 56,5 | 147 ms | 369 ms | 566 ms | 0,0 % | 100,0 % |
| 25 | 83,9 | 268 ms | 540 ms | 779 ms | 0,0 % | 100,0 % |
| 50 | 104,6 | 425 ms | 911 ms | 1,33 s | 0,0 % | 100,0 % |

Es el flujo que mejor escala: el rendimiento crece en todos los escalones, hasta 104,6 req/s, con p95 por debajo de 1 s. Sin errores.

### measurement_sync

| VUs | req/s | p50 | p95 | p99 | errores | replays → 200 |
|---|---|---|---|---|---|---|
| 5 | 29,4 | 150 ms | 326 ms | 580 ms | 0,0 % | 100,0 % |
| 10 | 50,5 | 163 ms | 410 ms | 635 ms | 0,0 % | 100,0 % |
| 25 | 83,3 | 271 ms | 547 ms | 749 ms | 0,0 % | 100,0 % |
| 50 | 84,9 | 531 ms | 1,07 s | 1,43 s | 0,0 % | 100,0 % |

Saturación entre 25 y 50 VUs: el rendimiento casi no cambia (83,3 → 84,9 req/s) y el p50 se duplica (271 → 531 ms). Sin errores.

### food_intake_sync

| VUs | req/s | p50 | p95 | p99 | errores | replays → 200 |
|---|---|---|---|---|---|---|
| 5 | 29,1 | 156 ms | 292 ms | 490 ms | 0,0 % | 100,0 % |
| 10 | 46,6 | 179 ms | 426 ms | 635 ms | 0,0 % | 100,0 % |
| 25 | 72,0 | 311 ms | 621 ms | 842 ms | 0,0 % | 100,0 % |
| 50 | 65,6 | 701 ms | 1,38 s | 1,78 s | 0,0 % | 100,0 % |

Con 50 VUs el rendimiento baja (72,0 → 65,6 req/s) y la latencia más que se duplica (p50 311 → 701 ms): el punto de saturación está en torno a 25 VUs. Sin errores.

### survey_response_sync

| VUs | req/s | p50 | p95 | p99 | errores | replays → 200 |
|---|---|---|---|---|---|---|
| 5 | 28,1 | 147 ms | 394 ms | 769 ms | 0,0 % | 100,0 % |
| 10 | 37,1 | 184 ms | 641 ms | 1,88 s | 0,0 % | 100,0 % |
| 25 | 34,0 | 411 ms | 2,54 s | 6,76 s | 0,0 % | 100,0 % |
| 50 | 41,3 | 840 ms | 2,89 s | 9,83 s | 0,0 % | 100,0 % |

Ya a 10 VUs el rendimiento deja de crecer de forma útil (37,1 req/s; 34,0 a 25 VUs y 41,3 a 50 VUs) mientras la latencia sigue subiendo. La cola de latencia es muy pesada: con 25 VUs el p99 es 6,76 s y el máximo de la corrida (escrituras) es 18,4 s. Sin errores, pero con tiempos que en un celular probablemente provocarían timeouts y reintentos (esto último no se midió).

## 3. Comparación entre flujos

Mismo nivel de concurrencia (req/s, p95):

| VUs | listings | subject_sync | measurement_sync | food_intake_sync | survey_response_sync |
|---|---|---|---|---|---|
| 10 | 63,1 / 234 ms | 56,5 / 369 ms | 50,5 / 410 ms | 46,6 / 426 ms | 37,1 / 641 ms |
| 25 | 75,1 / 597 ms | 83,9 / 540 ms | 83,3 / 547 ms | 72,0 / 621 ms | 34,0 / 2,54 s |
| 50 | 93,1 / 1,01 s | 104,6 / 911 ms | 84,9 / 1,07 s | 65,6 / 1,38 s | 41,3 / 2,89 s |

- **Más costoso:** `survey_response_sync`, por mucho: entre 2 y 3 veces menos req/s que los demás a 25 y 50 VUs y p99 de segundos.
- **Menos costosos:** `subject_sync` (el mejor a 25 y 50 VUs) y, a bajas cargas, `listings` (p95 de 165 ms con 5 VUs y 234 ms con 10).
- Los archivos no contienen el código ni los planes de consulta, así que lo que sigue son **hipótesis**: `survey_response_sync` podría escribir más filas o tablas por pedido, o validar/calcular algo costoso; `food_intake_sync` y `measurement_sync` podrían actualizar contadores o calcular alertas (bloqueos sobre filas compartidas); `listings` podría contar sobre tablas grandes para la paginación. Con solo 10 establecimientos y 10 trabajadores, la contención sobre filas compartidas (por establecimiento) es verosímil.
- Con 5 VUs los cinco flujos están entre 28,1 y 35,8 req/s, con p50 entre 138 y 156 ms: la latencia base es parecida, y la diferencia aparece con la concurrencia.

## 4. Idempotencia

- Los reenvíos devolvieron `200` en el 100,0 % de los casos en todos los escalones de los 4 flujos de escritura.
- Todos los checks de k6 pasaron, sin ninguna falla: 33.112 en `subject_sync`, 29.756 en `measurement_sync`, 25.603 en `food_intake_sync`, 16.863 en `survey_response_sync` y 32.049 en `listings`. El threshold `checks: rate==1` se cumplió en todos los flujos.
- Latencia de reenvíos frente a primeras escrituras (toda la corrida del flujo):

| Flujo | Escritura p50 / p95 / p99 | Replay p50 / p95 / p99 |
|---|---|---|
| subject_sync | 296 / 733 / 1156 ms | 186 / 597 / 909 ms |
| measurement_sync | 296 / 865 / 1249 ms | 177 / 689 / 1002 ms |
| food_intake_sync | 324 / 1043 / 1518 ms | 213 / 866 / 1239 ms |
| survey_response_sync | 373 / 1715 / 6789 ms | 147 / 998 / 2643 ms |

- Los reenvíos son más rápidos que las primeras escrituras en los cuatro flujos (p50 entre 35 % y 61 % menor), como cabe esperar si solo leen. Pero siguen siendo costosos: p50 de 147 a 213 ms, bastante por encima de una lectura simple. En `survey_response_sync` los reenvíos también sufren la cola larga (p99 2,64 s).
- `listings`: las métricas de `kind:write` y `kind:replay` valen 0 por no aplicar a este flujo.

## 5. Capacidad

Supuestos: un VU envía pedidos sin pausa, mientras una persona real alterna entre registrar datos y sincronizar; un trabajador que sincroniza una tanda genera ráfagas, pero muy pocos pedidos por minuto en promedio. Por eso 1 VU equivale a **más** de un trabajador. No se conoce el tamaño de las tandas ni el tiempo entre pedidos reales, así que lo siguiente es un orden de magnitud, no una promesa.

- Punto de saturación observado: 25 VUs para `food_intake_sync` y `measurement_sync`; 10 VUs para `survey_response_sync`; `subject_sync` y `listings` siguen creciendo hasta 50 VUs pero con p95 cercano a 1 s.
- Tomando como criterio p95 < 1 s: la capacidad es de unos 25 VUs en los flujos de sincronización más lentos (p95 de 540 a 621 ms) y apenas por encima de 10 VUs para `survey_response_sync` (p95 de 641 ms con 10 VUs y 2,54 s con 25).
- Interpretación: **entre 10 y 25 trabajadores sincronizando exactamente al mismo tiempo, de forma continua**, es el rango que la API sostiene con latencias razonables en las encuestas y los consumos. Con pausas reales entre pedidos, la cantidad de trabajadores simultáneos tolerables sería mayor, pero estos datos no permiten cuantificarla.
- Todos los pedidos vienen de una sola IP y de una sola máquina generadora; en producción las conexiones vendrían de muchas IP.

## 6. Posibles cuellos de botella (hipótesis)

| Hipótesis | Por qué es consistente con los datos | Qué medición la confirmaría |
|---|---|---|
| Un solo proceso de uvicorn (el `Dockerfile` no pasa `--workers`) | Un único event loop usa un solo núcleo para todo el trabajo de Python (validación, serialización). Al llenarse, el rendimiento se aplana y la latencia crece con los VUs, sin errores, que es lo que muestran las tablas. | CPU del proceso durante cada escalón; repetir con 2 o más workers. |
| Pool de conexiones agotado (por defecto 5 + 10 de desborde = 15) | El rendimiento se aplana entre 10 y 25 VUs, y a partir de ahí la latencia crece más o menos de forma proporcional a los VUs sin errores: forma de cola. | Métrica de conexiones en uso/espera del pool y `pg_stat_activity` durante cada escalón; repetir la prueba con un pool mayor. |
| Consulta o escritura lenta específica en `survey_response_sync` | Es el único flujo con p99 de varios segundos y máximo de 18,4 s desde 10 VUs, y con un rendimiento que no mejora con más VUs. | `EXPLAIN (ANALYZE)` de las consultas del endpoint; `pg_stat_statements`; trazas por pedido. |
| Bloqueos de filas o contadores compartidos por establecimiento | Hay solo 10 establecimientos y 10 trabajadores; las colas largas aparecen en los flujos que podrían actualizar contadores o alertas. | `pg_locks` y tiempos de espera de bloqueo durante la prueba; probar con más establecimientos sembrados. |
| Conteo para paginación en `listings` | La latencia p50 se duplica de 10 a 25 VUs con un aumento pequeño de rendimiento. | `EXPLAIN` de las consultas de listado con y sin el conteo total; comparar con tablas más grandes. |
| Límite de CPU de la base | No hay datos de recursos en los archivos. | CPU, memoria y E/S de PostgreSQL durante cada escalón. |
| Limitación del propio generador de carga | Todos los pedidos salen de una sola máquina. | CPU del generador durante la prueba; repetir con dos generadores. |

## 7. Recomendaciones

Ordenadas por impacto esperado:

1. **Investigar `survey_response_sync`** (consultas, bloqueos y tamaño de las escrituras): es donde está el mayor problema, con p99 de 6,76 s a 25 VUs.
2. **Medir CPU del proceso y el pool de conexiones**, y probar con más workers de uvicorn y un pool mayor; son los ajustes más baratos y, si las hipótesis son ciertas, mueven todos los flujos.
3. **Agregar métricas de recursos** (CPU, memoria, conexiones activas y en espera, bloqueos) a la corrida, para dejar de depender de hipótesis.
4. **Revisar los índices y los contadores/alertas** en `food_intake_sync` y `measurement_sync`, y el conteo de `listings`.
5. **Hacer más rápidos los reenvíos**, con una búsqueda por el id del dispositivo, indexada, antes de cualquier otro trabajo (p50 de 147 a 213 ms).
6. **Repetir la prueba** con commit identificado, escalones intermedios (15, 20, 35 VUs) y con pausas entre pedidos.

Presupuestos propuestos (a partir de estos números, para hasta 10 VUs, y a validar):

| Flujo | p95 | p99 | Errores |
|---|---|---|---|
| listings | ≤ 300 ms | ≤ 500 ms | 0 % |
| subject_sync | ≤ 400 ms | ≤ 600 ms | 0 % |
| measurement_sync | ≤ 450 ms | ≤ 700 ms | 0 % |
| food_intake_sync | ≤ 450 ms | ≤ 700 ms | 0 % |
| survey_response_sync | ≤ 650 ms (hoy 641 ms) | ≤ 1 s (hoy 1,88 s) | 0 % |
| Reenvíos (replay) | `200` en el 100 % | — | — |

A 25 VUs, el objetivo razonable sería p95 ≤ 1 s en todos los flujos; hoy solo `survey_response_sync` no lo cumple.

## 8. Limitaciones de esta corrida

- Un solo generador de carga desde una única IP; su propia capacidad no se midió.
- Sin pausas entre pedidos: mide el máximo, no el comportamiento de personas reales.
- Datos sembrados chicos (10 establecimientos, 10 trabajadores, 2.000 sujetos, 3 mediciones cada uno); los tiempos podrían empeorar con tablas más grandes.
- Escalones de 120 s: pocos datos para percentiles altos (p99 y máximos) y sin ver degradación a largo plazo. Entre escalones hay 5 s de pausa para que terminen los últimos pedidos, pero un escalón puede heredar efectos del anterior (caché, datos escritos).
- Las tasas por escalón incluyen la carga de datos que dejan los escalones previos (las escrituras se acumulan durante el flujo).
- Las req/s se calculan sobre los 120 s del escalón, pero incluyen los pedidos que terminan durante los 5 s de gracia: pueden quedar algo infladas.
- Sin métricas de CPU, memoria ni conexiones a la base en los archivos.
- `target_revision` es `null`: no se sabe qué commit de la API se probó. `failed` está vacío.
- No se conoce el hardware ni dónde corre la API; nada de este informe lo asume.
