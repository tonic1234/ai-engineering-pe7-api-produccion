"""supervisor.py: el nodo Supervisor: el router que decide quién trabaja y cuándo se cierra.

Tres cosas que vale la pena mirar:

1. La decisión es ESTRUCTURADA (un Pydantic con `Literal["investigador", "analista",
   "FINISH"]`). No parseo texto libre: así el valor que sale de acá se puede mapear
   directo a los nombres de los nodos en las aristas condicionales, sin adivinar.
2. El prompt lleva la RÚBRICA (eso que pide la consigna) y, sobre todo, lleva las
   CONTRIBUCIONES: el supervisor decide viendo quién aportó qué. Es la defensa contra la
   "pérdida de contexto en la comunicación asíncrona".
3. Hay un CORTE DURO por cantidad de pasos: si `pasos >= MAX_PASOS` devuelve FINISH sin
   consultar al modelo. Es la primera red contra el "Supervisor Infinito" (las otras dos
   son el validador determinista y el contador de reintentos, en graph.py).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from llm_factory import texto
from validation import validar_estado

# Cuántos especialistas como máximo antes de cerrar sí o sí.
MAX_PASOS = 6

# Instrucciones de reemplazo cuando hay que corregir una delegación repetida. Están
# escritas por oficio: al analista se le pide una CUENTA, no una búsqueda.
INSTRUCCION_POR_DEFECTO = {
    "investigador": (
        "Buscá en las políticas internas de la empresa el dato que falta para responder la "
        "pregunta y devolvelo textual, con su fuente entre corchetes."
    ),
    "analista": (
        "Calculá con los números que ya están en el contexto la cuenta que responde la "
        "pregunta original: multiplicá cada tramo por la cantidad de años que le corresponde "
        "y sumá el total. Devolvé el resultado de la calculadora."
    ),
}

SUPERVISOR_PROMPT = """Sos el Supervisor de un equipo con dos especialistas:

- investigador: busca datos concretos de la empresa (políticas internas: vacaciones,
  teletrabajo, seguridad informática, onboarding) usando su herramienta de búsqueda.
- analista: hace cálculos matemáticos con los números que ya se obtuvieron.

Rúbrica para aprobar el trabajo del equipo (contestar FINISH solo si TODOS se cumplen):
1. El pedido original está respondido, no una parte.
2. Si hacía falta un dato de la empresa, ese dato está en las contribuciones, con su fuente.
3. Si hacía falta una cuenta, el resultado del cálculo está en las contribuciones.
4. Ninguna contribución quedó en error ("ERROR:" o "No se encontró"): en ese caso hay que
   mandar al especialista otra vez, con una instrucción distinta (más específica).

Reglas de delegación:
- Si falta un dato de la empresa, elegí "investigador".
- Si ya está el dato y falta la cuenta, elegí "analista".
- Si un especialista YA aportó y su aporte no tiene error, NO lo elijas de nuevo: elegí el
  otro especialista o FINISH.
- Si se cumple la rúbrica, elegí "FINISH".

En `instruccion` escribí, en una o dos frases, QUÉ tiene que hacer exactamente el agente
que elegiste. Esa instrucción es la única que va a recibir el especialista, así que tiene
que ser concreta, autosuficiente y de SU oficio:

- si elegís "investigador", la instrucción arranca con "Buscá..." y pide el dato textual
  con su fuente. NUNCA le pidas una cuenta.
- si elegís "analista", la instrucción arranca con "Calculá..." y dice qué cuenta hacer
  con los números que ya están en el contexto. NUNCA le pidas buscar ni transcribir.

Contribuciones hasta ahora:
{contribuciones}
"""


class DecisionSupervisor(BaseModel):
    """Salida estructurada del supervisor: a quién llamar, para qué y por qué."""

    next: Literal["investigador", "analista", "FINISH"] = Field(
        description="Próximo agente a invocar, o FINISH si la tarea ya cumple la rúbrica"
    )
    instruccion: str = Field(
        default="",
        description=(
            "Instrucción concreta y autosuficiente para el agente elegido (qué tiene que "
            "hacer exactamente). Se ignora si next es FINISH."
        ),
    )
    razon: str = Field(
        min_length=5,
        description="Justificación breve de la decisión (por qué ese agente y no otro)",
    )

    # Validación explícita, no decorativa: una delegación SIN instrucción deja al especialista
    # adivinando qué hacer (y así fue como el analista terminó "buscando"). Si el supervisor
    # delega, tiene que decir qué y con qué alcance.
    @model_validator(mode="after")
    def _delegacion_con_instruccion(self):
        if self.next != "FINISH" and len(self.instruccion.strip()) < 10:
            raise ValueError(
                f"Falta la instrucción para {self.next}: tiene que explicar qué hacer, en una "
                "o dos frases (mínimo 10 caracteres)."
            )
        return self


class Supervisor:
    """Envuelve el LLM con salida estructurada y aplica el corte por pasos."""

    def __init__(self, llm=None, max_pasos: int = MAX_PASOS) -> None:
        self.max_pasos = max_pasos
        self._llm = llm
        self._cadena = None  # se construye en la primera decisión real (import perezoso)

    @property
    def cadena(self):
        if self._cadena is None:
            llm = self._llm
            if llm is None:
                from llm_factory import get_llm

                llm = get_llm()
            self._cadena = llm.with_structured_output(DecisionSupervisor)
        return self._cadena

    def decidir(self, state) -> DecisionSupervisor:
        """Devuelve la próxima acción. Ojo: el corte por pasos va ANTES de tocar el LLM."""

        pasos = state.get("pasos", 0) or 0
        if pasos >= self.max_pasos:
            return DecisionSupervisor(
                next="FINISH",
                razon=f"Se alcanzó el máximo de {self.max_pasos} pasos: cierro para no dar vueltas.",
            )

        contribuciones = state.get("contribuciones") or []
        resumen = "\n".join(
            f"- {c.get('agente')}: {texto(c.get('aporte', ''))[:200]}" for c in contribuciones
        ) or "(ninguna todavía)"

        pregunta_original = ""
        mensajes = state.get("messages") or []
        if mensajes:
            pregunta_original = texto(mensajes[0].content if hasattr(mensajes[0], "content") else mensajes[0])

        return self.cadena.invoke(
            [
                {"role": "system", "content": SUPERVISOR_PROMPT.format(contribuciones=resumen)},
                {"role": "user", "content": f"Tarea original: {pregunta_original}"},
            ]
        )


def _corregir_decision(state, decision: DecisionSupervisor) -> DecisionSupervisor:
    """Red determinista contra la delegación repetida y contra el cierre prematuro.

    Dos cosas aprendidas en las corridas reales, las dos con el mismo remedio:

    1. El modelo elegía "investigador" aunque su aporte ya estuviera en el estado, así que
       el analista nunca llegaba a correr (y la cuenta la terminaba inventando el nodo de
       síntesis).
    2. Al revés también: decidía FINISH con un dominio sin cubrir, y el flujo se iba a
       síntesis con media respuesta.

    Si el supervisor pide un especialista que YA aportó de forma verificable y falta el otro
    dominio, lo redirijo; y si quiere cerrar cuando todavía falta un dominio (y ya hay
    trabajo empezado), lo mando al que falta. El corte sigue estando: MAX_PASOS y
    MAX_REINTENTOS en graph.py, así que esto no puede dar vueltas para siempre.
    """

    informe = validar_estado(state)
    faltantes = informe["faltantes"]

    # Si la rúbrica YA se cumple, no hay nada más que delegar: se cierra. Sin esta regla el
    # supervisor podía pedir "un poco más" después de tener todo lo necesario. Pasó en una
    # corrida real: tres rondas de investigación de más para una pregunta que ya estaba
    # respondida. El validador es el que manda, también para cerrar.
    if informe["suficiente"]:
        return DecisionSupervisor(
            next="FINISH",
            razon="La rúbrica ya se cumple: no hay nada más que delegar.",
        )

    if decision.next == "FINISH":
        # Cerrar sin aportes (por ejemplo una pregunta que no necesita al equipo) es válido:
        # lo maneja el validador y se va a síntesis. Cerrar con un dominio a medio hacer, no.
        if faltantes and (state.get("contribuciones") or []):
            elegido = faltantes[0]
            return DecisionSupervisor(
                next=elegido,
                instruccion=INSTRUCCION_POR_DEFECTO[elegido],
                razon=f"El validador dice que falta {elegido}: no se cierra todavía.",
            )
        return decision

    ya_aporto = decision.next in informe["dominios_con_aporte"]
    restantes = [d for d in faltantes if d != decision.next]

    if ya_aporto and restantes:
        elegido = restantes[0]
        return DecisionSupervisor(
            next=elegido,
            instruccion=INSTRUCCION_POR_DEFECTO[elegido],
            razon=f"Corrijo la delegación: {decision.next} ya aportó y falta {elegido}.",
        )
    return decision


def nodo_supervisor(state, supervisor: Optional[Supervisor] = None) -> dict:
    """Nodo del grafo: escribe en el estado a quién hay que llamar y con qué instrucción."""

    supervisor = supervisor or Supervisor()
    decision = _corregir_decision(state, supervisor.decidir(state))
    return {
        "next_agent": decision.next,
        "instruccion": decision.instruccion,
        "task_completed": decision.next == "FINISH",
    }
