# SPEC — Norvia RAG (Prueba técnica TopDevCrew)

> Documento de trabajo interno. Traduce el enunciado oficial a requisitos verificables
> y registra lo que debemos decidir. Las decisiones finales y sus justificaciones
> viven en `DECISIONS.md`; las ambigüedades confirmadas se moverán allí.

## 0. Contexto y objetivo

**Norvia Seguros** (aseguradora ficticia) quiere que sus gestores de siniestros consulten
condiciones de pólizas y circulares internas en **lenguaje natural**.

- Modelo **multi-inquilino**: cada corredora (**tenant**) sube sus propios PDFs y **solo**
  puede consultar los suyos (aislamiento estricto).
- Entregable: **monorepo público en GitHub** con backend, workers, frontend e infraestructura.

Stack objetivo: **FastAPI + Celery (broker Redis) + PostgreSQL/pgvector + React**, con
**trazabilidad OpenTelemetry** extremo a extremo.

---

## 1. Restricciones del ejercicio (no negociables)

| # | Restricción |
|---|---|
| C1 | **72 horas** desde el envío. Deadline: **5 nov 2026, 23:20 UTC**. |
| C2 | **Una sola entrega**: se congela el último commit al pegar el link. Commits posteriores se ignoran. |
| C3 | **Un único repositorio PÚBLICO de GitHub** (monorepo). No privados, no múltiples repos, no zip. |
| C4 | Se defiende el código en entrevista → **entregar solo lo que entendamos**. |
| C5 | Ambigüedades: decidir y justificar en `DECISIONS.md`. |
| C6 | Debe correr **sin claves externas** (proveedores falsos deterministas por defecto). |
| C7 | **Sin secretos en el repo.** |

---

## 2. Requisitos funcionales (EXIGIDOS)

### R1 — Ingesta asíncrona
- **F1.1** Endpoint FastAPI de **subida de PDF por tenant** que devuelva **de inmediato** un
  identificador de trabajo (`job_id`) y **encole** la ingesta en Celery.
- **F1.2** Endpoint de **consulta de estado** del trabajo: `pendiente | procesando | completado | fallido`.

### R2 — Pipeline de ingesta (worker Celery)
- **F2.1** Extracción de texto **con número de página**.
- **F2.2** Fragmentación (**chunking**) **con solapamiento**.
- **F2.3** Generación de **embeddings**.
- **F2.4** Persistencia en **PostgreSQL/pgvector** con **índice vectorial**.
- **F2.5** **Idempotencia**: ante reintentos y ante subida repetida del mismo archivo
  (no duplicar fragmentos/embeddings).

### R3 — Recuperación (retrieval)
- **F3.1** Recuperación **acotada por tenant** (nunca cruza inquilinos).
- **F3.2** **Híbrida**: combinar similitud vectorial + búsqueda de texto de PostgreSQL,
  **o** justificar por escrito por qué no.

### R4 — Endpoint de preguntas (QA)
- **F4.1** Construye el prompt con los **fragmentos recuperados**.
- **F4.2** Devuelve respuesta **validada con Pydantic**: `respuesta`, `citas`, `nivel de confianza`.
- **F4.3** **Citas verificables**: documento, página, fragmento.
- **F4.4** **Streaming opcional** de la respuesta.
- **F4.5** Comportamiento ante **evidencia insuficiente**: responder **"no se sabe"** en lugar
  de inventar.
- **F4.6** Verificar que **cada cita apunta a un fragmento realmente recuperado**.

### R5 — Abstracción de proveedores (LLM + embeddings)
- **F5.1** Capa de abstracción con **implementación falsa determinista**.
- **F5.2** Implementación **real configurable** por variables de entorno (ej. **Gemini vía LiteLLM**
  o adaptador propio).
- **F5.3** **Timeouts**, **reintentos con espera** (backoff) y **manejo de límites de uso** (rate limits).

### R6 — Frontend React
- **F6.1** TypeScript recomendado.
- **F6.2** **Subida de archivos**.
- **F6.3** **Lista de documentos** con estado **actualizado**.
- **F6.4** **Chat** que muestre las **citas** junto a cada respuesta.

### R7 — Evaluación
- **F7.1** Script/comando de evaluación que mida **acierto de recuperación** (ej. **recall@k**)
  sobre las preguntas del corpus sintético.
- **F7.2** Imprime un **informe reproducible**.

### R8 — Datos sintéticos
- **F8.1** Pequeño **corpus de documentos sintéticos**.
- **F8.2** Conjunto de **preguntas de evaluación**.

---

## 3. Nivel de calidad (EXIGIDO)

### Q1 — Pruebas automatizadas
- **Q1.1** Unitarias: **fragmentación** y **validación de citas**.
- **Q1.2** Integración con **PostgreSQL+pgvector real** (ej. testcontainers o Docker Compose).
- **Q1.3** Prueba de **aislamiento**: un tenant **no puede** recuperar datos de otro.

### Q2 — Manejo de fallos
- **Q2.1** PDFs **corruptos o vacíos**.
- **Q2.2** **Caída del proveedor de LLM**.
- **Q2.3** Reintentos de Celery con **cola de mensajes fallidos (DLQ)** o estado final claro.
- **Q2.4** Respuestas de **error de la API consistentes**.

### Q3 — Observabilidad (OpenTelemetry)
- **Q3.1** Una **traza** que atraviese **API → tarea Celery → consulta a BD → llamada al LLM**.
- **Q3.2** **Propagación de contexto a través de la cola** (Redis/Celery).
- **Q3.3** Atributos útiles: **tenant, latencia, tokens**.
- **Q3.4** Exportación por **OTLP o a consola**.

### Q4 — Seguridad
- **Q4.1** **Autenticación por tenant** sencilla (ej. API key o JWT).
- **Q4.2** Validación de **tipo y tamaño** de archivo.
- **Q4.3** **Sin secretos** en el repo.
- **Q4.4** **Mitigación razonada de inyección de prompt** desde el contenido de los documentos.

### Q5 — Infraestructura
- **Q5.1** Todo el sistema levantable con **un solo comando de Docker Compose**
  (API, worker, Redis, PostgreSQL, frontend).
- **Q5.2** **CI con GitHub Actions**: ejecuta **linters** y **pruebas**.

### Q6 — Logging
- **Q6.1** Logs **estructurados** con **identificador de correlación**.
- **Q6.2** **No** volcar el contenido completo de los documentos ni las preguntas de los usuarios.

---

## 4. Decisiones a justificar (EXIGIDO en DECISIONS.md)

- **D1** Estrategia de **fragmentación y recuperación** (tamaño, solapamiento, híbrida vs
  solo vectorial, reordenamiento/reranking): cuál y con qué **evidencia de la evaluación**.
- **D2** **Aislamiento multi-inquilino**: filtro por columna vs esquemas separados vs
  **RLS** en PostgreSQL. Justificar simplicidad / rendimiento / riesgo de fuga.
- **D3** **Versionado / borrado de documentos**: reindexar, versionar o invalidar citas
  antiguas. Definir comportamiento y costes.
- **D4** Métricas en **producción**: calidad de respuestas y **coste por consulta**; qué queda
  **fuera de alcance** por tiempo.

---

## 5. Entregables (EXIGIDO)

- **E1** Monorepo público en GitHub: backend, workers, frontend, infra (Docker Compose + CI).
- **E2** `README.md`: ejecutar todo desde cero, lanzar pruebas y evaluación, qué está hecho,
  qué no, y limitaciones conocidas.
- **E3** `DECISIONS.md`: responde las preguntas abiertas (D1–D4), trade-offs, y **cómo usamos
  IA generativa y cómo verificamos** lo producido.
- **E4** Pruebas automatizadas (unitarias, integración, aislamiento) ejecutables en local y CI.
- **E5** Corpus sintético + preguntas de evaluación + **informe de resultados de recuperación**.
- **E6** Capturas o descripción breve en README de una **traza OTel completa** de una consulta
  (API → LLM).

---

## 6. Flujos clave (entendimiento compartido)

### Flujo de ingesta
```
Cliente (tenant X) --POST /upload--> API FastAPI
    API: valida tipo/tamaño/autenticación, guarda archivo, crea Job(status=pendiente),
         encola tarea Celery, responde 202 { job_id }
    Worker Celery: status=procesando → extrae texto+páginas → chunking c/ overlap
         → embeddings → upsert idempotente en pgvector → status=completado|fallido
Cliente --GET /jobs/{job_id}--> estado actual
```

### Flujo de pregunta
```
Cliente (tenant X) --POST /ask { question }--> API
    Retrieval acotado a tenant X (vector + full-text híbrido) → top-k fragmentos
    Construye prompt con fragmentos → LLM (fake|real) → salida Pydantic
    Valida que cada cita ∈ fragmentos recuperados
    Si evidencia insuficiente → "no se sabe"
    Respuesta { respuesta, citas[{doc, página, fragmento}], confianza } (+ streaming opcional)
```

---

## 7. Preguntas abiertas / ambigüedades a confirmar

> Resueltas → ver tabla y §§ D1–D4 en `DECISIONS.md` (hosting GitHub público, adaptador
> propio, API key+JWT, RLS, chunking 900/150 + híbrido, uv, Vite+TS, Compose para
> integración, cortes D4, docs/código en inglés).

---

## 8. Checklist de trazabilidad requisito → implementación

> Se completará a medida que avancemos (cada ítem debe tener prueba o evidencia).

- [x] R1 Ingesta asíncrona (F1.1, F1.2) — `POST /upload`, `GET /jobs/{id}`
- [x] R2 Pipeline + idempotencia (F2.1–F2.5)
- [x] R3 Retrieval por tenant + híbrido (F3.1, F3.2)
- [x] R4 QA + Pydantic + citas + "no sé" (F4.1–F4.6) — streaming en `/ask/stream`
- [x] R5 Abstracción proveedores fake/real (F5.1–F5.3)
- [x] R6 Frontend React (F6.1–F6.4) — upload, job polling, chat + citations
- [x] R7 Evaluación recall@k (F7.1, F7.2) — `python -m eval.run` → `eval/reports/latest.md`
- [x] R8 Corpus + preguntas (F8.1, F8.2) — `corpus/documents` + `corpus/questions.json`
- [x] Q1 Tests (unit/integración/aislamiento) — Compose Postgres + RLS fail-closed
- [x] Q2 Manejo de fallos — corrupt PDF / provider retry / job failed; API error envelope
- [x] Q3 OpenTelemetry extremo a extremo — API→Celery(ctx sobre Redis)→BD→LLM, exporter
      consola/OTLP (`app/core/telemetry.py`); spans manuales con tenant/latencia/tokens
- [x] Q4 Seguridad (auth API key+JWT, validación upload, anti prompt-injection en prompt)
- [x] Q5 Docker Compose único + CI
- [x] Q6 Logging estructurado con correlación — structlog + `X-Request-ID` propagado a
      Celery; redacción de contenido/pregunta (len/hash/preview), nunca texto completo
- [x] D1–D4 justificados en `DECISIONS.md` (D3 policy decided; confirm/soft-delete **code gap**)
- [x] E1–E6 Entregables — E6: traza OTel; E3 incluye sección «How we use generative AI»
