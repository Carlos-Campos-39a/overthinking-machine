"""
decentralized.py — Multi-Agent System: Decentralized (MAS-Decentralized)

Definição (Kim et al., 2025):
    A = {a_1, ..., a_n}, C = {(a_i, a_j): ∀i,j, i≠j}, Ω = consensus
    LLM calls: O(dnk), Sequential depth = d·n, Memory = O(d·n·k)
    Consensus via debate rounds

Estrutura:
    1. Todos os n agentes produzem resposta inicial independente
    2. d rounds de debate: cada agente vê respostas dos outros e revisa
    3. Resposta final = resposta do agente 1 após último round de debate
       (proxy para consenso — equivalente a majority voting em classificação)

Vantagem: exploração paralela de alto entropia (ótimo para web browsing +9.2%)
Risco: degrada em tarefas sequenciais (-39% a -70% em planning)
"""
from __future__ import annotations
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from src.agents.agent_base import AgentBase, AgentTrace
from src.llm_text import texto_da_resposta


class DecentralizedMAS(AgentBase):
    """
    MAS Descentralizado: peer-to-peer debate sem hierarquia.

    Topologia: all-to-all (cada agente vê as respostas de todos os outros).
    Consensus: o agente 1 dá a resposta final após d rounds.
    """

    name = "decentralized"

    def __init__(
        self,
        llm: BaseChatModel,
        n_agents: int = 3,
        debate_rounds: int = 1,
    ):
        super().__init__()
        self.llm = llm
        self.n_agents = n_agents
        self.debate_rounds = debate_rounds

    def run(self, messages: list[BaseMessage]) -> str:
        self.last_trace = []
        step = 0

        system_content = self._extract_system(messages)
        task_content = self._extract_human(messages)

        # ── Round 0: Respostas iniciais independentes ─────────────────────
        current_responses: list[str] = []

        for i in range(self.n_agents):
            agent_id = f"agent_{i+1}"
            perspective_prompt = (
                f"{task_content}\n\n"
                f"[Perspectiva {i+1}/{self.n_agents}: analise a partir de um ângulo "
                f"{'crítico e conservador' if i == 0 else 'otimista e prospectivo' if i == 1 else 'equilibrado e baseado em dados'}]"
            )

            self.last_trace.append(AgentTrace(
                agent_id=agent_id,
                role="human",
                content=perspective_prompt,
                step=step,
                metadata={"round": 0},
            ))

            response = self.llm.invoke([
                SystemMessage(content=system_content),
                HumanMessage(content=perspective_prompt),
            ])
            output = texto_da_resposta(response)
            current_responses.append(output)
            step += 1

            self.last_trace.append(AgentTrace(
                agent_id=agent_id,
                role="assistant",
                content=output,
                step=step,
                metadata={"round": 0, "usage": self._usage(response)},
            ))

        # ── Rounds de debate ──────────────────────────────────────────────
        for round_num in range(1, self.debate_rounds + 1):
            new_responses: list[str] = []

            for i in range(self.n_agents):
                agent_id = f"agent_{i+1}"

                # Monta peer context (respostas dos outros agentes)
                peer_context = "\n\n".join(
                    f"--- Resposta do Agente {j+1} ---\n{resp}"
                    for j, resp in enumerate(current_responses)
                    if j != i
                )

                debate_prompt = (
                    f"TAREFA ORIGINAL:\n{task_content}\n\n"
                    f"SUA RESPOSTA ANTERIOR (Round {round_num-1}):\n{current_responses[i]}\n\n"
                    f"RESPOSTAS DOS OUTROS AGENTES:\n{peer_context}\n\n"
                    f"Revise sua resposta incorporando insights válidos dos outros agentes. "
                    f"Mantenha seus pontos corretos e corrija erros identificados. "
                    f"Produza uma resposta revisada e aprimorada."
                )

                self.last_trace.append(AgentTrace(
                    agent_id=agent_id,
                    role="human",
                    content=debate_prompt,
                    step=step,
                    metadata={"round": round_num},
                ))

                response = self.llm.invoke([
                    SystemMessage(content=system_content),
                    HumanMessage(content=debate_prompt),
                ])
                output = texto_da_resposta(response)
                new_responses.append(output)
                step += 1

                self.last_trace.append(AgentTrace(
                    agent_id=agent_id,
                    role="assistant",
                    content=output,
                    step=step,
                    metadata={"round": round_num, "usage": self._usage(response)},
                ))

            current_responses = new_responses

        # ── Consensus: agente 1 como resposta final ───────────────────────
        # Ou pede que agente 1 produza síntese de consenso
        final_output = current_responses[0]

        # Marca o último trace entry como final
        if self.last_trace:
            self.last_trace[-1].metadata["is_final"] = True

        # Se temos múltiplas respostas finais, gera síntese de consenso
        if self.n_agents > 1 and self.debate_rounds > 0:
            consensus_prompt = (
                f"TAREFA:\n{task_content}\n\n"
                f"Após {self.debate_rounds} round(s) de debate entre {self.n_agents} agentes, "
                f"estas são as respostas finais:\n\n"
                + "\n\n".join(
                    f"--- Agente {j+1} ---\n{resp}"
                    for j, resp in enumerate(current_responses)
                )
                + "\n\nProduza a resposta de consenso final, representando o melhor "
                  "entendimento coletivo após o debate."
            )

            self.last_trace.append(AgentTrace(
                agent_id="consensus",
                role="human",
                content=consensus_prompt,
                step=step,
                metadata={"round": "consensus"},
            ))

            consensus_response = self.llm.invoke([
                SystemMessage(content=system_content),
                HumanMessage(content=consensus_prompt),
            ])
            final_output = texto_da_resposta(consensus_response)
            step += 1

            self.last_trace.append(AgentTrace(
                agent_id="consensus",
                role="assistant",
                content=final_output,
                step=step,
                metadata={"is_final": True, "round": "consensus", "usage": self._usage(consensus_response)},
            ))

        return final_output
