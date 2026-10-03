"""Human-in-the-loop: qué tareas se pausan y cómo se destraban.

La decisión de pausar no puede quedar "a criterio del modelo" (no es auditable ni repetible):
se decide en código, con dos reglas que se pueden leer y testear:
  1. la instrucción pide una acción con efecto (publicar, escribir, enviar, borrar...);
  2. el costo estimado del paso supera el umbral configurado.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.esquemas import EstadoJob

UMBRAL_COSTO_APROBACION = float(os.getenv("UMBRAL_COSTO_APROBACION", "0.02"))

# Raíces de verbos en infinitivo/imperativo: alcanzan con el prefijo para cubrir las variantes
# ("publicá", "publicar", "publicando"). Es a propósito que sea una lista corta y revisable.
VERBOS_DE_EFECTO = (
    "public",
    "escrib",
    "envi",
    "manda",
    "borr",
    "elimin",
    "contrat",
    "firm",
    "modific",
    "actualiz",
    "despleg",
    "pagar",
    "transfer",
    "archiv",
    "subi",
    "reemplaz",
)


def es_critica(instruccion: str | None, costo_estimado: float | None = None) -> tuple[bool, str]:
    """Devuelve (si hay que pedir aprobación, por qué)."""
    texto = (instruccion or "").lower()
    for verbo in VERBOS_DE_EFECTO:
        if verbo in texto:
            return True, f"la instrucción pide una acción con efecto ('{verbo}')"
    if costo_estimado is not None and costo_estimado >= UMBRAL_COSTO_APROBACION:
        return True, (
            f"el costo estimado ({costo_estimado:.4f} US$) llega al umbral "
            f"({UMBRAL_COSTO_APROBACION:.4f} US$)"
        )
    return False, ""


def _momento(texto: str | None) -> datetime:
    if not texto:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        return datetime.now(timezone.utc)


async def vencer_aprobaciones(cola, minutos: float | None = None) -> list[str]:
    """Cierra las aprobaciones que nadie contestó (si no, quedan colgadas para siempre)."""
    limite = float(minutos if minutos is not None else os.getenv("MINUTOS_ESPERA_APROBACION", "15"))
    corte = datetime.now(timezone.utc) - timedelta(minutes=limite)
    vencidos: list[str] = []
    for job_id in await cola.por_estado(EstadoJob.ESPERANDO_APROBACION):
        datos = await cola.leer(job_id)
        if datos and _momento(datos.get("actualizada_en")) <= corte:
            await cola.actualizar(
                job_id,
                EstadoJob.RECHAZADO_POR_TIMEOUT,
                error=f"la aprobación no llegó en {limite:g} minutos",
            )
            vencidos.append(job_id)
    return vencidos
