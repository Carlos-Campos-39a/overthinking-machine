"""
hybrid.py — Multi-Agent System: Hybrid (MAS-Hybrid)

Definição (Kim et al., 2025):
    A = {a_orch, a_1, ..., a_n}, C = C_centralized ∪ C_peer, Ω = hierarchical + lateral
    LLM calls: O(rnk + pn), Sequential depth = r, Parallelization = n
    Overhead: O(r·n·k + p·n) — combina hierarquia com debate peer-to-peer

Estrutura:
    1. Orchestrator decompõe a tarefa em subtarefas (como Centralized)
    2. Workers executam subtarefas individualmente
    3. Workers fazem p rounds de debate peer-to-peer entre si (como Decentralized)
    4. Orchestrator sintetiza os outputs refinados pelo debate

Vantagem: combina validation bottleneck do centralizado + exploração do descentralizado
Ideal para: tarefas com componentes paralelos que se beneficiam de validação cruzada
"""
from __future__ import annotations
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from src.agents.agent_base import AgentBase, AgentTrace
from src.agents.parse_subtarefas import parse_subtarefas
from src.llm_text import texto_da_resposta


class HybridMAS(AgentBase):
    """
    MAS Híbrido: hierarquia orquestradora + debate peer entre workers.

    Fluxo: Orchestrator → Workers (independentes) → Peer debate (p rounds) → Orchestrator síntese
    """

    name = "hybrid"

    def __init__(
        self,
        llm: BaseChatModel,
        n_workers: int = 3,
        debate_rounds: int = 1,
        peer_rounds: int | None = None,   # alias legado — use debate_rounds
        orchestrator_llm: BaseChatModel | None = None,
    ):
        super().__init__()
        self.worker_llm = llm
        self.orchestrator_llm = orchestrator_llm or llm
        self.n_workers = n_workers
        # Aceita tanto debate_rounds (padrão) quanto peer_rounds (legado)
        self.peer_rounds = peer_rounds if peer_rounds is not None else debate_rounds

    def run(self, messages: list[BaseMessage]) -> str:
        self.last_trace = []
        step = 0

        system_content = self._extract_system(messages)
        task_content = self._extract_human(messages)

        # ── Step 1: Orchestrator decompõe ────────────────────────────────
        decompose_prompt = (
            f"Você é um orquestrador especialista. Decomponha a tarefa abaixo em "
            f"exatamente {self.n_workers} subtarefas independentes e complementares.\n\n"
            f"TAREFA:\n{task_content}\n\n"
            f"Responda com {self.n_workers} subtarefas numeradas (1 a {self.n_workers}), "
            f"uma por linha. Cada subtarefa deve ser autocontida."
        )

        self.last_trace.append(AgentTrace(
            agent_id="orchestrator",
            role="human",
            content=decompose_prompt,
            step=step,
            metadata={"phase": "decompose"},
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
            metadata={"phase": "decompose", "usage": self._usage(decompose_response)},
        ))

        subtasks = self._parse_subtasks(subtasks_raw, task_content)

        # ── Step 2: Workers executam subtarefas ───────────────────────────
        worker_outputs: list[str] = []

        for i, subtask in enumerate(subtasks):
            worker_id = f"worker_{i+1}"
            step += 1

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
                metadata={"phase": "worker_initial"},
            ))

            response = self.worker_llm.invoke([
                SystemMessage(content=system_content),
                HumanMessage(content=worker_prompt),
            ])
            output = texto_da_resposta(response)
            worker_outputs.append(output)
            step += 1

            self.last_trace.append(AgentTrace(
                agent_id=worker_id,
                role="assistant",
                content=output,
                step=step,
                metadata={"phase": "worker_initial", "usage": self._usage(response)},
            ))

        # ── Step 3: Peer debate entre workers ─────────────────────────────
        for peer_round in range(1, self.peer_rounds + 1):
            refined_outputs: list[str] = []

            for i in range(self.n_workers):
                worker_id = f"worker_{i+1}"

                # Peers = outros workers
                peer_context = "\n\n".join(
                    f"--- Worker {j+1} (subtarefa: {subtasks[j][:100]}) ---\n{worker_outputs[j]}"
                    for j in range(self.n_workers)
                    if j != i
                )

                peer_prompt = (
                    f"TAREFA ORIGINAL:\n{task_content}\n\n"
                    f"SUA SUBTAREFA:\n{subtasks[i]}\n\n"
                    f"SUA RESPOSTA ATUAL:\n{worker_outputs[i]}\n\n"
                    f"ANÁLISES DOS WORKERS PARCEIROS (Round {peer_round}):\n{peer_context}\n\n"
                    f"Refine sua análise considerando os pontos válidos dos parceiros. "
                    f"Foque em sua subtarefa mas incorpore contexto relevante dos outros. "
                    f"Mantenha o formato de resposta exigido pela tarefa original."
                )

                step += 1
                self.last_trace.append(AgentTrace(
                    agent_id=worker_id,
                    role="human",
                    content=peer_prompt,
                    step=step,
                    metadata={"phase": "peer_debate", "round": peer_round},
                ))

                response = self.worker_llm.invoke([
                    SystemMessage(content=system_content),
                    HumanMessage(content=peer_prompt),
                ])
                output = texto_da_resposta(response)
                refined_outputs.append(output)
                step += 1

                self.last_trace.append(AgentTrace(
                    agent_id=worker_id,
                    role="assistant",
                    content=output,
                    step=step,
                    metadata={"phase": "peer_debate", "round": peer_round, "usage": self._usage(response)},
                ))

            worker_outputs = refined_outputs

        # ── Step 4: Orchestrator síntese final ────────────────────────────
        synthesis_parts = "\n\n".join(
            f"=== Worker {i+1} (após {self.peer_rounds} round(s) de debate) ===\n{result}"
            for i, result in enumerate(worker_outputs)
        )
        synthesis_prompt = (
            f"TAREFA ORIGINAL:\n{task_content}\n\n"
            f"Os workers produziram as seguintes análises após debate peer-to-peer:\n\n"
            f"{synthesis_parts}\n\n"
            f"Sintetize em uma resposta final coesa, completa e sem redundâncias. "
            f"Aproveite a complementaridade das análises. "
            f"Responda diretamente, sem mencionar workers, rounds ou o processo."
        )

        step += 1
        self.last_trace.append(AgentTrace(
            agent_id="orchestrator",
            role="human",
            content=synthesis_prompt,
            step=step,
            metadata={"phase": "synthesis"},
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
            metadata={"phase": "synthesis", "is_final": True, "usage": self._usage(final_response)},
        ))

        return final_output

    def _parse_subtasks(self, raw: str, fallback: str) -> list[str]:
        # Parser compartilhado com o interpretador declarativo — ver
        # src/agents/parse_subtarefas.py.
        return parse_subtarefas(raw, fallback, self.n_workers)
