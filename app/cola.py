"""La cola y el estado de los trabajos, guardados en Redis.

Dos claves por trabajo: el hash `job:<id>` con todo su estado, y la lista `tareas:cola` que es
el buzón del worker. El estado se escribe ANTES de encolar: si el worker gana la carrera y el
cliente consulta primero, igual encuentra el trabajo (si no, ve un 404 que parece un bug).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis

from app.esquemas import EstadoJob

TTL_SEGUNDOS = int(os.getenv("JOB_TTL_SEGUNDOS", str(24 * 60 * 60)))
COLA = "tareas:cola"
PREFIJO = "job:"
INDICE = "tareas:indice"


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ColaRedis:
    def __init__(self, url: str | None = None, cliente=None):
        self.cliente = cliente or redis.from_url(
            url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True
        )

    # --- claves ---------------------------------------------------------------

    def clave(self, job_id: str) -> str:
        return f"{PREFIJO}{job_id}"

    # --- ciclo de vida del trabajo -------------------------------------------

    async def crear(self, pregunta: str, job_id: str | None = None) -> str:
        """Guarda el estado pendiente y recién después encola."""
        job_id = job_id or uuid.uuid4().hex[:12]
        momento = ahora()
        await self.cliente.hset(
            self.clave(job_id),
            mapping={
                "job_id": job_id,
                "pregunta": pregunta,
                "estado": EstadoJob.PENDIENTE.value,
                "pasos": 0,
                "contribuciones": json.dumps([], ensure_ascii=False),
                "creada_en": momento,
                "actualizada_en": momento,
            },
        )
        await self.cliente.expire(self.clave(job_id), TTL_SEGUNDOS)
        await self.cliente.sadd(INDICE, job_id)
        await self.cliente.lpush(COLA, job_id)
        return job_id

    async def leer(self, job_id: str) -> dict | None:
        datos = await self.cliente.hgetall(self.clave(job_id))
        if not datos:
            return None
        if datos.get("contribuciones"):
            try:
                datos["contribuciones"] = json.loads(datos["contribuciones"])
            except json.JSONDecodeError:
                datos["contribuciones"] = []
        if datos.get("pasos") is not None:
            try:
                datos["pasos"] = int(datos["pasos"])
            except (TypeError, ValueError):
                datos["pasos"] = 0
        return datos

    async def actualizar(self, job_id: str, estado: EstadoJob, **campos) -> dict:
        """Deja el estado nuevo (y lo que venga) y devuelve cómo quedó el trabajo."""
        if "contribuciones" in campos and not isinstance(campos["contribuciones"], str):
            campos["contribuciones"] = json.dumps(campos["contribuciones"], ensure_ascii=False)
        campos["estado"] = estado.value
        campos["actualizada_en"] = ahora()
        await self.cliente.hset(self.clave(job_id), mapping={k: v for k, v in campos.items() if v is not None})
        return await self.leer(job_id)

    async def tomar(self, timeout_s: float = 1.0) -> str | None:
        """Saca el próximo trabajo de la cola. No bloquea el event loop."""
        return await self.cliente.lpop(COLA)

    async def encolar(self, job_id: str) -> None:
        await self.cliente.lpush(COLA, job_id)

    async def pendientes(self) -> int:
        return await self.cliente.llen(COLA)

    async def por_estado(self, estado: EstadoJob) -> list[str]:
        ids = await self.cliente.smembers(INDICE)
        encontrados = []
        for job_id in sorted(ids):
            datos = await self.leer(job_id)
            if datos and datos.get("estado") == estado.value:
                encontrados.append(job_id)
        return encontrados

    # --- salud y limpieza ----------------------------------------------------

    async def esta_viva(self) -> bool:
        try:
            return bool(await self.cliente.ping())
        except Exception:  # noqa: BLE001: el health tiene que contestar, no explotar
            return False

    async def limpiar_todo(self) -> None:
        for job_id in await self.cliente.smembers(INDICE):
            await self.cliente.delete(self.clave(job_id))
        await self.cliente.delete(INDICE, COLA)
