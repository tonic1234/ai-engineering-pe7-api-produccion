"""Arranca el worker como proceso aparte: `python -m app.worker_main`.

La API y el worker comparten sólo Redis: no hay nada en memoria que los una. Por eso se pueden
correr varios workers, reiniciar uno sin tocar la API y reanudar un trabajo pausado en otro
proceso (los checkpoints del grafo están en Redis).
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.cola import ColaRedis
from app.ejecutor import EjecutorDelGrafo
from app.observabilidad import activar_trazas
from app.worker import correr_worker


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")

    # El worker también instrumenta: es el proceso donde corre el grafo, así que si esto faltara
    # el dashboard mostraría la API pero ninguna traza de los agentes.
    activar_trazas()

    cola = ColaRedis()
    ejecutor = EjecutorDelGrafo()
    print(f"worker escuchando la cola; concurrencia={os.getenv('WORKER_CONCURRENCIA', '3')}", flush=True)
    try:
        await correr_worker(cola, ejecutor)
    finally:
        await ejecutor.cerrar()


if __name__ == "__main__":
    asyncio.run(main())
