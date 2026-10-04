"""Las 5 peticiones concurrentes que pide la consigna (dos tandas, para que el p95 diga algo).

Habla con la API por HTTP, como un cliente de verdad: POST /tareas, después polling del estado.
No importa los módulos del proyecto para no esconder los problemas de la API detrás de una
llamada en proceso.

Uso:
    python scripts/carga.py                 # dos tandas de 5
    python scripts/carga.py --tanda 5       # una sola tanda de 5
    python scripts/carga.py --api http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone

import httpx

PREGUNTAS = [
    "Un colaborador cumplió 12 años en la empresa: 2 años con menos de 3 de antigüedad, 6 años con entre 3 y 8, y 4 años con más de 8. ¿Cuántos días de vacaciones le correspondieron en total?",
    "¿Qué pasa con los días de vacaciones que quedaron sin usar al cerrar el año y cuántos días corresponden a alguien con 5 años de antigüedad?",
    "¿Cuántos días de licencia por estudio corresponden por año y qué requisitos de antigüedad pide la política de teletrabajo?",
    "Alguien con 9 años de antigüedad: 4 años con menos de 3, 3 años con entre 3 y 8 y 2 años con más de 8. ¿Cuántos días de vacaciones acumuló?",
    "¿Se puede tomar vacaciones en enero? ¿Y cuántos días corresponden a alguien con 2 años en la empresa?",
    "Resumí las condiciones del teletrabajo y calculá los días de vacaciones de una persona con 8 años exactos de antigüedad.",
    "¿Qué dice la política de seguridad sobre el uso de equipos personales y cuántos días de vacaciones tiene alguien con 15 años en la empresa?",
    "Un equipo de 3 personas con 2, 6 y 11 años de antigüedad. ¿Cuántos días de vacaciones suman entre los tres?",
    "¿Cómo funciona el período de prueba para nuevos ingresos y cuántos días de vacaciones corresponden a alguien con 3 años justos?",
    "¿La política permite vender días de vacaciones no gozados? Si alguien con 20 años tiene 10 días sin usar, ¿cuántos le quedarían?",
]


async def una(cliente: httpx.AsyncClient, pregunta: str, indice: int, intervalo: float = 0.5) -> dict:
    inicio = time.perf_counter()
    respuesta = await cliente.post("/tareas", json={"pregunta": pregunta})
    respuesta.raise_for_status()
    job_id = respuesta.json()["job_id"]
    t_post = time.perf_counter() - inicio

    esperando_aprobacion = False
    estado = "pendiente"
    while True:
        await asyncio.sleep(intervalo)
        informe = (await cliente.get(f"/tareas/{job_id}")).json()
        estado = informe["estado"]
        if estado == "esperando_aprobacion":
            esperando_aprobacion = True
        if estado in {"done", "fallo", "rechazado", "rechazado_por_timeout"}:
            return {
                "indice": indice,
                "job_id": job_id,
                "estado": estado,
                "segundos": round(time.perf_counter() - inicio, 1),
                "segundos_del_post": round(t_post, 3),
                "pasos": informe.get("pasos"),
                "contribuciones": len(informe.get("contribuciones") or []),
                "esperando_aprobacion": esperando_aprobacion,
                "error": informe.get("error"),
                "respuesta": (informe.get("resultado") or "")[:120],
            }


def percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    posicion = (len(ordenados) - 1) * p
    abajo, arriba = int(posicion), min(int(posicion) + 1, len(ordenados) - 1)
    return round(ordenados[abajo] + (ordenados[arriba] - ordenados[abajo]) * (posicion - abajo), 1)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--tanda", type=int, default=5)
    parser.add_argument("--tandas", type=int, default=2)
    parser.add_argument("--salida", default="")  # archivo JSON opcional
    args = parser.parse_args()

    resultados: list[dict] = []
    tandas: list[dict] = []

    async with httpx.AsyncClient(base_url=args.api, timeout=600) as cliente:
        for numero in range(1, args.tandas + 1):
            preguntas = PREGUNTAS[(numero - 1) * args.tanda: numero * args.tanda]
            inicio = time.perf_counter()
            print(f"\n=== tanda {numero}: {len(preguntas)} peticiones concurrentes ===", flush=True)
            tanda = await asyncio.gather(
                *(una(cliente, pregunta, i, intervalo=0.5) for i, pregunta in enumerate(preguntas))
            )
            duracion = round(time.perf_counter() - inicio, 1)
            resultados.extend(tanda)
            ok = [r["segundos"] for r in tanda if r["estado"] == "done"]
            tandas.append(
                {
                    "tanda": numero,
                    "duracion_total": duracion,
                    "peticiones": len(tanda),
                    "ok": len(ok),
                    "errores": len(tanda) - len(ok),
                    "p50": percentil(ok, 0.5),
                    "p95": percentil(ok, 0.95),
                    "min": min(ok) if ok else None,
                    "max": max(ok) if ok else None,
                    "post_mas_lento": max(r["segundos_del_post"] for r in tanda),
                }
            )
            for r in tanda:
                print(f"  [{r['indice']}] {r['estado']:<10} {r['segundos']:>6}s  post {r['segundos_del_post']}s  {r['job_id']}", flush=True)

    print("\n=== resumen ===")
    for t in tandas:
        print(
            f"tanda {t['tanda']}: {t['ok']}/{t['peticiones']} ok en {t['duracion_total']}s | "
            f"p50 {t['p50']}s | p95 {t['p95']}s | POST más lento {t['post_mas_lento']}s"
        )

    todas = [r["segundos"] for r in resultados if r["estado"] == "done"]
    resumen = {
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api": args.api,
        "tandas": tandas,
        "total_peticiones": len(resultados),
        "ok": len(todas),
        "p50_global": percentil(todas, 0.5),
        "p95_global": percentil(todas, 0.95),
        "mediana_de_la_mediana": round(statistics.median(todas), 1) if todas else None,
        "resultados": resultados,
    }
    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as archivo:
            json.dump(resumen, archivo, ensure_ascii=False, indent=2)
        print(f"\nresultado guardado en {args.salida}")

    return 0 if len(todas) == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
