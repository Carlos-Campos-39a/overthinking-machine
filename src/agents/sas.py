"""
sas.py — Single Agent System (SAS)

Definição (Kim et al., 2025):
    |A| = 1, C = ∅ (sem comunicação inter-agente)
    Complexidade: O(k) chamadas LLM, O(k) profundidade sequencial
    Overhead de coordenação: 0

O SAS é o baseline inferior — todas as comparações com MAS são relativas a ele.
Mantém contexto completo em stream unificado, minimizando fragmentação de contexto.
"""
from __future__ import annotations
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from src.agents.agent_base import AgentBase, AgentTrace
from src.llm_text import texto_da_resposta


class SingleAgentSystem(AgentBase):
    """
    SAS: um único LLM, uma única chamada de inferência.

    Recebe as mensagens do harness diretamente e retorna a resposta.
    Overhead de coordenação = 0 (sem mensagens inter-agente).
    """

    name = "sas"

    def __init__(self, llm: BaseChatModel):
        super().__init__()
        self.llm = llm

    def run(self, messages: list[BaseMessage]) -> str:
        self.last_trace = []

        # Log das mensagens de entrada
        for i, msg in enumerate(messages):
            self.last_trace.append(AgentTrace(
                agent_id="agent",
                role=msg.__class__.__name__.replace("Message", "").lower(),
                content=msg.content,
                step=i,
            ))

        # Única chamada LLM
        response = self.llm.invoke(messages)
        output = texto_da_resposta(response)

        self.last_trace.append(AgentTrace(
            agent_id="agent",
            role="assistant",
            content=output,
            step=len(messages),
            metadata={"usage": self._usage(response)},
        ))

        return output
