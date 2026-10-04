# API de producción y monitoreo activo (pre-entrega 7)

Este repo agarra el orquestador multi-agente de la pre-entrega 6 y lo pone a funcionar como un
servicio: una API que recibe la consulta, la encola y devuelve un id al instante, un worker que
corre el grafo por detrás, el estado de cada trabajo guardado en Redis y las trazas de las
corridas en un dashboard de Phoenix.

La idea de fondo es la de la unidad del módulo: un flujo de agentes tarda entre 30 y 120 segundos
(acá tardó entre 28 y 115, están las mediciones más abajo), así que no puede vivir dentro de una
petición HTTP. Si el request se queda esperando al equipo de agentes, cualquier timeout del camino
lo corta y el servidor se queda sin recursos. La salida es separar: la API recibe y encola, el
worker ejecuta, y quien preguntó consulta el estado.

## Cómo se usa

Cuatro endpoints:

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/tareas` | Recibe `{"pregunta": "..."}` y devuelve 202 con el `job_id` |
| GET | `/tareas/{job_id}` | El estado del trabajo y, si terminó, la respuesta |
| POST | `/tareas/{job_id}/aprobar` | Aprueba o rechaza una tarea que quedó esperando |
| GET | `/health` | Si Redis contesta y qué modelo está configurado |

Un trabajo pasa por estos estados:

```
pendiente ─▶ en_proceso ─▶ esperando_aprobacion ─▶ aprobado ─▶ done
                      │                          │
                      └─▶ fallo                  └─▶ rechazado / rechazado_por_timeout
```

`fallo` guarda el motivo (por ejemplo un 429 del proveedor). Sin ese paso, si el agente se cae en
segundo plano el cliente quedaría consultando para siempre.

## Levantarlo

Con Docker, que trae Redis con los módulos de búsqueda (los necesita el checkpointer del grafo) y
Phoenix ya listos:

```bash
cp .env.example .env         # completá GOOGLE_API_KEY, y lo de Pinecone si lo tenés
docker compose up --build
```

Queda la API en `http://localhost:8000` y el dashboard de Phoenix en `http://localhost:6006`.

Sin Docker, con Redis y Phoenix corriendo aparte:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # y requirements-dev.txt para las pruebas

export REDIS_URL=redis://127.0.0.1:6379/0
export PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces

phoenix serve --host 127.0.0.1 --port 6006     # terminal 1 (dashboard de trazas)
uvicorn app.main:app --host 127.0.0.1 --port 8000   # terminal 2 (la API)
python -m app.worker_main                      # terminal 3 (el worker)
```

Son tres procesos a propósito: la API y el worker no comparten nada en memoria, sólo Redis. Por
eso se puede reiniciar cualquiera de los dos sin perder trabajo, y una tarea aprobada se reanuda
en otro proceso (los checkpoints del grafo están en Redis).

## Un trabajo, paso a paso

```bash
# 1. se manda la consulta: contesta en milisegundos, sin correr nada
curl -s -X POST localhost:8000/tareas -H 'content-type: application/json' \
  -d '{"pregunta":"¿Cuántos días de vacaciones corresponden a alguien con 5 años de antigüedad y qué dice la política de teletrabajo?"}'
# {"job_id":"b330e27b92f8","estado":"pendiente"}

# 2. se consulta el estado (lo que haría la interfaz cada pocos segundos)
curl -s localhost:8000/tareas/b330e27b92f8
# {"job_id":"b330e27b92f8","estado":"en_proceso",...}

# 3. cuando termina, el mismo endpoint trae la respuesta
curl -s localhost:8000/tareas/b330e27b92f8
# {"estado":"done","resultado":"...","pasos":2,"contribuciones":[...]}
```

Si la consulta pide una acción con efecto, el trabajo no llega a `done` solo: queda esperando la
aprobación con la instrucción a la vista. Esta es la salida real de una corrida (la consulta pedía
"enviar por correo el resumen"):

```bash
curl -s localhost:8000/tareas/ae7a06d57526
```
```json
{"job_id":"ae7a06d57526","estado":"esperando_aprobacion",
 "pregunta":"Enviá por correo el resumen de la política de seguridad informática y decime cuántos días de vacaciones tiene alguien con 4 años de antigüedad.",
 "resultado":null,"error":null,"pasos":0,"contribuciones":[],
 "instruccion_pendiente":"Buscá la política de seguridad informática para resumirla y la política de vacaciones que detalle la cantidad de días correspondientes según los años de antigüedad, incluyendo sus fuentes.",
 "hilo_id":"b8b1b873b304",
 "creada_en":"2026-10-04T23:36:25+00:00","actualizada_en":"2026-10-04T23:36:29+00:00"}
```

Fijate que el trabajo quedó en `pasos: 0`: no se ejecutó nada del equipo, la instrucción está
esperando. Recién con la aprobación sigue:

```bash
curl -s -X POST localhost:8000/tareas/ae7a06d57526/aprobar \
  -H 'content-type: application/json' -d '{"aprobado":true,"comentario":"adelante"}'
# {"job_id":"ae7a06d57526","estado":"aprobado"}

# y un rato después, el mismo GET de la consulta del estado
# {"estado":"done","pasos":2,"contribuciones":[{"agente":"investigador"},{...}]}
```

Aprobar algo que no está esperando devuelve 409 con el estado en el que está, y no un 200 mudo.

## La prueba de carga (5 concurrentes)

`scripts/carga.py` manda las peticiones por HTTP, como un cliente de verdad, y va consultando el
estado de cada una:

```bash
python scripts/carga.py --salida carga.json
```

Corrida del 4-oct-2026 contra Gemini, dos tandas de 5 concurrentes:

| Tanda | Peticiones | OK | Duración total | p50 | p95 | POST más lento |
|---|---|---|---|---|---|---|
| 1 | 5 | 5 | 197,5 s | 85,4 s | 177,4 s | 0,08 s |
| 2 | 5 | 5 | 105,1 s | 46,3 s | 95,1 s | 0,039 s |

Dos cosas que salen de la tabla. Primero: el POST tarda milisegundos mientras el trabajo completo
tarda decenas de segundos, que es el punto de encolar en vez de ejecutar en el request. Segundo:
con 5 peticiones el p95 es casi el máximo, así que corrí dos tandas; con una sola el número no dice
nada.

## Qué se ve en Phoenix

Con `PHOENIX_COLLECTOR_ENDPOINT` configurado, cada nodo del grafo deja su span: el supervisor, la
búsqueda en las políticas, la calculadora, la validación y la síntesis. Las capturas de la corrida
están en `screenshots/`:

- `01-spans.png` — los spans de la corrida, con el gráfico de latencia del proyecto arriba.
- `02-traza-abierta.png` — una traza abierta: se ve el árbol (LangGraph → supervisor → aprobación →
  investigador → herramientas → modelo), y arriba a la derecha el costo y la latencia de esa traza.
- `03-latencia-costos.png` — la vista de métricas: los percentiles de latencia (p50 a p99) y el
  costo estimado en dólares de la corrida.
- `04-api-docs.png` — la API documentada y navegable que trae FastAPI (`/docs`), con los cuatro
  endpoints y los esquemas de entrada y salida.
- `05-aprobacion-humana.png` — el nodo `aprobacion` de una corrida real, con el input que lo
  reanudó: `{"resume": {"aprobado": true, "comentario": "ok, adelante"}}`. Es la pausa y la
  aprobación vistas desde el dashboard.

Dejar la instrumentación sólo sobre LangChain fue a propósito: Phoenix, si no, engancha también
FastAPI y cada consulta de estado del cliente deja su span, así que el dashboard se llena de
`GET /tareas/<id>` y las trazas del grafo quedan enterradas.

## Lo que dice el dashboard

Miré las trazas de todas las corridas (45 ejecuciones, 115 llamadas al modelo) y agrupé por tipo
de span. Los contenedores (`LangGraph`, `supervisor`) incluyen a sus hijos, así que sus segundos
no se suman a los de las llamadas: sirven para ver dónde está el peso.

| Tipo de span | Veces | Latencia acumulada | Tokens |
|---|---|---|---|
| LangGraph (cada corrida completa) | 45 | 963,6 s | — |
| ChatGoogleGenerativeAI (llamadas al modelo) | 115 | 524,7 s | 245.761 |
| supervisor (la decisión) | 43 | 272,6 s | (incluye su llamada) |
| buscar_en_politicas_internas (la herramienta) | 26 | 102,5 s | (incluye su llamada) |
| EnsembleRetriever (la recuperación en sí) | 20 | 16,2 s | — |
| aprobacion | 45 | 1,0 s | — |
| validacion | 12 | 0,5 s | — |

Lo que se lee ahí:

1. **La latencia está en el modelo, no en el resto.** De los 963 segundos acumulados de corridas,
   525 se van en las llamadas a Gemini (el 54%, con un promedio de 4,6 s y picos de 7,2 s). La
   recuperación híbrida tarda 0,8 s por consulta y la validación 0,04 s, porque es código.
   Si hubiera que bajar el p95 el camino no es optimizar el retriever: es hacer menos rondas de
   supervisor, que es lo que multiplica las llamadas.
2. **Los tokens los consumen las decisiones.** El supervisor llama al modelo en cada ronda para
   decidir a quién delega; la síntesis, una vez al final. En una corrida de dos dominios son 5 o 6
   llamadas: por eso el gasto por ejecución queda en el orden de un centavo.
3. **El nodo de aprobación no cuesta nada.** 45 pausas, 0,04 s de promedio y cero tokens: lo único
   que hace es frenar. Y mientras espera la aprobación, el grafo tampoco consume: en la traza de una
   corrida pausada se ve el hueco entre el último span antes de la pausa y el primero después.

La traza de una corrida que pasó por aprobación humana, en orden:

| # | Nodo | Latencia | Tokens |
|---|---|---|---|
| 1 | supervisor (decide delegar) | 4,4 s | 773 |
| 2 | aprobacion (pausa, espera permiso) | 0,0 s | 0 |
| 3 | investigador (búsqueda + redacción del aporte) | 33,6 s | 3.018 |
| 4 | supervisor (pide el cálculo) | 7,2 s | 2.417 |
| 5 | aprobacion (la tarea ya estaba aprobada) | 0,0 s | 0 |
| 6 | analista (calculadora + redacción) | 5,1 s | 2.539 |
| 7 | supervisor (cierra) | 2,0 s | 907 |
| 8 | validacion (¿la rúbrica se cumple?) | 0,0 s | 0 |
| 9 | sintesis (redacta la respuesta) | 3,4 s | 974 |

Esa corrida quedó pausada varios minutos esperando la aprobación, así que su traza dura mucho más
que el trabajo real del equipo: el tiempo de espera no aparece como span porque no consume nada.

## El grafo

```mermaid
graph TD;
	__start__([start]) --> supervisor;
	supervisor --> aprobacion;
	aprobacion -.-> investigador;
	aprobacion -.-> analista;
	aprobacion -.-> validacion;
	aprobacion -.-> sintesis;
	investigador --> supervisor;
	analista --> supervisor;
	validacion -.-> supervisor;
	validacion -.-> sintesis;
	sintesis --> __end__([end]);
```

Es la topología jerárquica de la pre-entrega 6 (el supervisor decide, los especialistas siempre
vuelven a él, no hay arista de investigador a analista), con un nodo de más entre el supervisor y
el especialista: `aprobacion`.

Ese nodo mira la instrucción que redactó el supervisor y el pedido original, y si aparece una
acción con efecto (publicar, escribir, enviar, borrar, contratar, firmar) o si el costo estimado
del paso pasa el umbral, pausa el grafo con `interrupt()`. La decisión se toma en código y no "a
criterio del modelo" porque tiene que ser auditable y repetible: la lista de verbos y el umbral
están en `app/hitl.py` y los cubre `tests/test_hitl.py`.

La aprobación se pide una sola vez por trabajo. Cuando llega, el grafo sigue desde el checkpoint y
las rondas siguientes del supervisor ya no vuelven a preguntar (me pasó en la primera corrida:
pedía permiso en cada ronda y no cerraba nunca). En `screenshots/05-aprobacion-humana.png` está el
nodo con el input que lo reanudó, leído del dashboard.

## Las pruebas (112, sin claves y sin red)

```bash
python -m pytest -q
........................................................................ [ 64%]
........................................                                 [100%]
112 passed in 121.02s (0:02:01)
```

Las pruebas del orquestador usan dobles en los tres lugares donde habría red (el modelo, la nube
vectorial y el recuperador), así que corren sin ninguna clave. Las de la capa de servicio usan un
Redis en memoria con la misma interfaz.

Dos detalles que salieron de las devoluciones anteriores y quedaron cubiertos por pruebas:

- un test compara la cantidad de pruebas que dice este README con la que realmente junta pytest:
  si alguien agrega o saca una y no actualiza el número, la suite falla;
- el estado de la cola se guarda ANTES de encolar el trabajo, y hay un test que espía el orden de
  los comandos contra Redis para que no se invierta. Si se invirtiera, el worker podría ganar la
  carrera y el cliente recibiría un 404 que parece un bug.

## Estructura

```
app/                 lo nuevo de esta entrega
  api.py             los endpoints (no corre nada: encola y contesta)
  cola.py            el estado de los trabajos y la cola, en Redis
  worker.py          el bucle que saca de la cola y corre el grafo
  worker_main.py     `python -m app.worker_main`
  ejecutor.py        el único módulo que sabe de LangGraph
  grafo.py           el grafo de producción (el de la 6 + el nodo de aprobación)
  hitl.py            la regla de qué es crítico y cómo se vencen las aprobaciones
  observabilidad.py  la instrumentación de Phoenix
  esquemas.py        los estados y los contratos de entrada y salida
  main.py            `uvicorn app.main:app`
agents/              los dos especialistas (investigación y análisis)
data/                las políticas internas del recuperador
scripts/carga.py     las 5 peticiones concurrentes
tests/               las pruebas
screenshots/         las capturas del dashboard
```

El orquestador (`graph.py`, `nodes.py`, `supervisor.py`, `validation.py`, `tools.py`, `rag.py`,
`state.py`, `llm_factory.py`) queda igual que en la pre-entrega 6: esta entrega no lo toca, lo
envuelve. `ingest.py` sigue siendo la única vía para cargar el índice vectorial.

## El dataset

Las políticas de `data/` son de una empresa ficticia y el texto está inventado: es el mismo corpus
de las pre-entregas 3 y 4, con la forma y las reglas que tendría un manual de RR.HH. real. No es
información de ninguna empresa.
