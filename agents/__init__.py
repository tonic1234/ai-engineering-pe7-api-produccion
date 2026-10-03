"""agents/__init__.py: los especialistas del equipo."""

from agents.analyst_agent import ANALISTA_PROMPT, build_analyst_agent
from agents.research_agent import INVESTIGADOR_PROMPT, build_research_agent

__all__ = [
    "build_research_agent",
    "build_analyst_agent",
    "INVESTIGADOR_PROMPT",
    "ANALISTA_PROMPT",
]
