"""
agent_base.py — Contrato base para todas as arquiteturas de agentes.

Baseado em: Kim et al. (2025) "Towards a Science of Scaling Agent Systems" (arXiv:2512.08296)
Formalização: S = (A, E, C, Ω)
  A = conjunto de agentes
  E = ambiente compartilhado
  C = topologia de comunicação
  Ω = política de orquestração

Cada arquitetura implementa run() e popula self.last_trace após cada chamada.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from langchain_core.messages import BaseMessage


@dataclass
class AgentTrace:
    """Um step no trace de execução do agente."""
    agent_id: str           # ex: "orchestrator", "worker_1", "worker_2"
    role: str               # "system", "human", "assistant"
    content: str
    step: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "content": self.content,
            "step": self.step,
            **self.metadata,
        }


class AgentBase(ABC):
    """
    Interface base para todas as arquiteturas.

    Subclasses implementam run() e devem popular self.last_trace
    com a sequência de steps para rastreabilidade no Meta-Harness.
    """

    name: str = ""

    def __init__(self):
        self.last_trace: list[AgentTrace] = []

    @abstractmethod
    def run(self, messages: list[BaseMessage]) -> str:
        """
        Executa o agente com as mensagens do harness.

        Args:
            messages: lista de BaseMessage construída pelo harness
                      (geralmente [SystemMessage, HumanMessage])

        Returns:
            Resposta final como string.

        Side effect:
            Popula self.last_trace com todos os steps de execução.
        """
        ...

    def trace_dicts(self) -> list[dict]:
        """Retorna o trace como lista de dicts serializáveis para JSONL."""
        return [t.to_dict() for t in self.last_trace]

    def _extract_system(self, messages: list[BaseMessage]) -> str:
        """Extrai conteúdo da SystemMessage, se presente."""
        from langchain_core.messages import SystemMessage
        for m in messages:
            if isinstance(m, SystemMessage):
                return m.content
        return ""

    def _extract_human(self, messages: list[BaseMessage]) -> str:
        """Extrai conteúdo da última HumanMessage."""
        from langchain_core.messages import HumanMessage
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return m.content
        return ""

    def _usage(self, response) -> dict:
        """Extrai contagem de tokens (input/output/total) da resposta do LLM, se disponível."""
        um = getattr(response, "usage_metadata", None)
        if not um:
            return {}
        return {
            "input_tokens": um.get("input_tokens", 0),
            "output_tokens": um.get("output_tokens", 0),
            "total_tokens": um.get("total_tokens", 0),
        }
