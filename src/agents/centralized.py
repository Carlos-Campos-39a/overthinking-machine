"""
centralized.py — Multi-Agent System: Centralized (MAS-Centralized)

Definição (Kim et al., 2025):
    A = {a_orch, a_1, ..., a_n}, C = {(a_orch, a_i): ∀i}, Ω = hierarchical
    LLM calls: O(rnk), Sequential depth = r, Parallelization = n
    Overhead: r·n mensagens orquestrador↔workers

Estrutura:
    1. Orchestrator recebe a tarefa e a decompõe em n subtarefas
    2. Cada worker executa sua subtarefa de forma independente
    3. Orchestrator sintetiza as respostas dos workers em resposta final

Vantagem: validation bottleneck reduz amplificação de erro (4.4× vs 17.2× no Independent)
Ideal para: tarefas paralelas com componentes independentes (ex: análise financeira multi-dimensão)
"""
from __future__ import annotations
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from src.agents.agent_base import AgentBase, AgentTrace
from src.llm_text import texto_da_resposta


class CentralizedMAS(AgentBase):
    """
    MAS Centralizado: orquestrador hierárquico + n workers paralelos.

    O orquestrador (Ω = hierarchical) coordina r rounds com n sub-agentes.
    Nesta implementação: r=1, n=n_workers (configurável).
    """

    name = "centralized"

    def __init__(
        self,
        llm: BaseChatModel,
        n_workers: int = 3,
        orchestrator_llm: BaseChatModel | None = None,
    ):
        super().__init__()
        self.worker_llm = llm
        self.orchestrator_llm = orchestrator_llm or llm
        self.n_workers = n_workers

    def run(self, messages: list[BaseMessage]) -> str:
        self.last_trace = []
        step = 0

        system_content = self._extract_system(messages)
        task_content = self._extract_human(messages)

        # ── Step 1: Orchestrator decompõe a tarefa ────────────────────────
        decompose_prompt = (
            f"Você é um orquestrador especialista. Decomponha a tarefa abaixo em "
            f"exatamente {self.n_workers} subtarefas independentes e complementares.\n\n"
            f"TAREFA PRINCIPAL:\n{task_content}\n\n"
            f"Responda APENAS com as {self.n_workers} subtarefas, uma por linha, "
            f"numeradas de 1 a {self.n_workers}. Cada subtarefa deve ser autocontida "
            f"e contribuir para a resposta final."
        )

        self.last_trace.append(AgentTrace(
            agent_id="orchestrator",
            role="human",
            content=decompose_prompt,
            step=step,
        ))

        decompose_response = self.orchestrator_llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=decompose_prompt),
        ])
        subtasks_raw = texto_da_resposta(decompose_response)
        step += 1

        self.last_trace.append(AgentTrace(
            agent_id="orchestrator",
            role="assistant",
            content=subtasks_raw,
            step=step,
            metadata={"usage": self._usage(decompose_response)},
        ))

        # Parse subtasks
        subtasks = self._parse_subtasks(subtasks_raw, task_content)

        # ── Step 2: Workers executam subtarefas ───────────────────────────
        worker_results = []
        for i, subtask in enumerate(subtasks):
            step += 1
            worker_id = f"worker_{i+1}"

            worker_prompt = (
                f"TAREFA ORIGINAL:\n{task_content}\n\n"
                f"SUA SUBTAREFA:\n{subtask}\n\n"
                f"Execute sua subtarefa considerando o contexto da tarefa original acima."
            )

            self.last_trace.append(AgentTrace(
                agent_id=worker_id,
                role="human",
                content=worker_prompt,
                step=step,
            ))

            worker_response = self.worker_llm.invoke([
                SystemMessage(content=system_content),
                HumanMessage(content=worker_prompt),
            ])
            worker_output = texto_da_resposta(worker_response)
            step += 1

            self.last_trace.append(AgentTrace(
                agent_id=worker_id,
                role="assistant",
                content=worker_output,
                step=step,
                metadata={"usage": self._usage(worker_response)},
            ))
            worker_results.append((i + 1, worker_output))

        # ── Step 3: Orchestrator sintetiza ────────────────────────────────
        synthesis_parts = "\n\n".join(
            f"=== Worker {i} ===\n{result}" for i, result in worker_results
        )
        synthesis_prompt = (
            f"Você recebeu análises de {self.n_workers} especialistas para a tarefa abaixo.\n\n"
            f"TAREFA ORIGINAL:\n{task_content}\n\n"
            f"ANÁLISES DOS WORKERS:\n{synthesis_parts}\n\n"
            f"Sintetize as análises em uma resposta final coesa, completa e sem redundâncias. "
            f"Resolva contradições usando seu próprio julgamento. "
            f"Responda diretamente sem mencionar os workers ou o processo de síntese."
        )

        step += 1
        self.last_trace.append(AgentTrace(
            agent_id="orchestrator",
            role="human",
            content=synthesis_prompt,
            step=step,
        ))

        final_response = self.orchestrator_llm.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=synthesis_prompt),
        ])
        final_output = texto_da_resposta(final_response)
        step += 1

        self.last_trace.append(AgentTrace(
            agent_id="orchestrator",
            role="assistant",
            content=final_output,
            step=step,
            metadata={"is_final": True, "usage": self._usage(final_response)},
        ))

        return final_output

    def _parse_subtasks(self, raw: str, fallback: str) -> list[str]:
        """Extrai subtarefas numeradas do output do orquestrador."""
        lines = [
            line.strip()
            for line in raw.splitlines()
            if line.strip() and line.strip()[0].isdigit()
        ]
        # Remove numeração (1. / 1) etc.)
        subtasks = []
        for line in lines:
            # Remove prefix "1." ou "1)" etc.
            cleaned = line.lstrip("0123456789.)- ").strip()
            if cleaned:
                subtasks.append(cleaned)

        # Fallback: se parse falhou, divide por parágrafo
        if not subtasks:
            paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
            subtasks = paragraphs or [fallback]

        # Garante exatamente n_workers subtasks
        while len(subtasks) < self.n_workers:
            subtasks.append(fallback)

        return subtasks[: self.n_workers]
