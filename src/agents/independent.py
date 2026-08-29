"""
independent.py — Multi-Agent System: Independent (MAS-Independent)

Definição (Kim et al., 2025):
    A = {a_1, ..., a_n}, C = {(a_i, a_agg): ∀i}, Ω = synthesis_only
    LLM calls: O(nk + 1), Sequential depth = k, Parallelization = n
    Overhead = mínimo (sem peer communication)

Estrutura:
    1. n agentes processam a mesma tarefa de forma completamente independente
    2. Aggregator sintetiza as respostas sem cross-validation
       (synthesis_only policy — sem majority voting ou analytical comparison)

Nota (Kim et al., 2025): Independent amplifica erros 17.2× por propagação não verificada.
Útil para medir o efeito puro de paralelismo sem coordenação.
"""
from __future__ import annotations
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from src.agents.agent_base import AgentBase, AgentTrace


class IndependentMAS(AgentBase):
    """
    MAS Independente: n agentes em paralelo + síntese sem cross-validation.

    Implementa Ω = synthesis_only: o aggregator concatena saídas sem análise
    comparativa, garantindo que as diferenças de performance em relação ao SAS
    venham exclusivamente do paralelismo e não da correção de erros.
    """

    name = "independent"

    def __init__(
        self,
        llm: BaseChatModel,
        n_agents: int = 3,
        aggregator_llm: BaseChatModel | None = None,
    ):
        super().__init__()
        self.llm = llm
        self.aggregator_llm = aggregator_llm or llm
        self.n_agents = n_agents

    def run(self, messages: list[BaseMessage]) -> str:
        self.last_trace = []
        step = 0

        system_content = self._extract_system(messages)
        task_content = self._extract_human(messages)

        # ── Step 1: Agentes independentes (sem comunicação entre si) ─────
        agent_outputs: list[str] = []

        for i in range(self.n_agents):
            agent_id = f"agent_{i+1}"

            # Cada agente recebe as mesmas mensagens originais — sem contexto de outros
            self.last_trace.append(AgentTrace(
                agent_id=agent_id,
                role="human",
                content=task_content,
                step=step,
            ))

            response = self.llm.invoke(messages)
            output = response.content.strip()
            agent_outputs.append(output)
            step += 1

            self.last_trace.append(AgentTrace(
                agent_id=agent_id,
                role="assistant",
                content=output,
                step=step,
                metadata={"usage": self._usage(response)},
            ))

        # ── Step 2: Aggregator — synthesis_only (sem cross-validation) ───
        # Concatena outputs sem análise comparativa (política do paper)
        aggregated_parts = "\n\n".join(
            f"=== Agente {i+1} ===\n{out}" for i, out in enumerate(agent_outputs)
        )

        synthesis_prompt = (
            f"TAREFA:\n{task_content}\n\n"
            f"Abaixo estão {self.n_agents} respostas independentes para esta tarefa. "
            f"Combine-as em uma resposta unificada e coerente.\n\n"
            f"{aggregated_parts}\n\n"
            f"Resposta combinada (sem mencionar que são múltiplas fontes):"
        )

        step += 1
        self.last_trace.append(AgentTrace(
            agent_id="aggregator",
            role="human",
            content=synthesis_prompt,
            step=step,
        ))

        final_response = self.aggregator_llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=synthesis_prompt),
        ])
        final_output = final_response.content.strip()
        step += 1

        self.last_trace.append(AgentTrace(
            agent_id="aggregator",
            role="assistant",
            content=final_output,
            step=step,
            metadata={"is_final": True, "usage": self._usage(final_response)},
        ))

        return final_output
