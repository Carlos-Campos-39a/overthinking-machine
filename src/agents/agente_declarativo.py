"""
agente_declarativo.py — executa uma topologia descrita por especificação.

É um AgentBase como qualquer outro: recebe a lista de mensagens do harness e
devolve uma string. A diferença é que o fluxo não está em código, e sim numa
EspecTopologia — o que permite alguém montar a própria topologia na interface
ou pelo MCP sem escrever Python, e sem que a plataforma execute código de
terceiro.

POR QUE ISSO NÃO EXIGIU MUDAR A INSTRUMENTAÇÃO: o runner conta tokens somando
`step.get("usage")` sobre os traces, e AgentTrace.to_dict() espalha o metadata
no nível de cima. Basta então que todo step de resposta carregue
`metadata={"usage": self._usage(resp)}` para que tokens, chamadas, latência,
custo, SSE e leaderboard continuem funcionando sem uma linha alterada em
runner.py, server.py ou no frontend.
"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from src.agents.agent_base import AgentBase, AgentTrace
from src.agents.parse_subtarefas import parse_subtarefas
from src.agents.topologia_spec import (
    EspecTopologia,
    Estagio,
    renderizar,
    validar_topologia,
)
from src.llm_text import texto_da_resposta


class AgenteDeclarativo(AgentBase):
    """Interpretador de topologias declarativas."""

    name = "declarativo"

    def __init__(self, llm: BaseChatModel, spec: EspecTopologia | dict, **_ignorado: Any):
        super().__init__()
        # Revalida sempre — inclusive vinda do banco. Uma spec guardada foi
        # validada quando entrou, mas os limites podem ter mudado desde então,
        # e confiar no que está no disco é como confiar no corpo da requisição.
        self.spec = validar_topologia(spec)
        self.llm = llm
        self.name = self.spec.nome

    # ── execução ─────────────────────────────────────────────────────────────

    def run(self, messages: list[BaseMessage]) -> str:
        self.last_trace = []
        self._passo = 0

        system_content = self._extract_system(messages)
        task_content = self._extract_human(messages)

        ctx_base = {
            "task_content":   task_content,
            "system_content": system_content,
        }
        # Referência cruzada entre estágios: o estágio que decompõe precisa dizer
        # "divida em N partes", mas quem tem esse N é o estágio de workers, mais
        # adiante. {n:worker} e {rodadas:debate} resolvem isso sem que a
        # linguagem precise de um passe de resolução separado.
        for outro in self.spec.estagios:
            ctx_base[f"n:{outro.id}"] = outro.n
            ctx_base[f"rodadas:{outro.id}"] = outro.rodadas

        # saída de cada estágio: str (unico/reduzir) ou list[str] (paralelo/debate)
        saidas: dict[str, str | list[str]] = {}
        self._saidas = saidas
        # as subtarefas mais recentes; o debate do hybrid precisa delas depois
        # que o estágio que as gerou já passou
        subtarefas: list[str] = []
        final_texto = ""

        for pos, est in enumerate(self.spec.estagios):
            origem = est.de or (self.spec.estagios[pos - 1].id if pos else None)
            entrada = saidas.get(origem) if origem else task_content

            if est.dividir:
                base = entrada if isinstance(entrada, str) else "\n".join(entrada or [])
                subtarefas = parse_subtarefas(base, task_content, est.n)

            if est.tipo == "unico":
                saida = self._chamada(est, messages, system_content, {
                    **ctx_base, "i": 1, "n": 1,
                    "resposta_anterior": self._texto(entrada),
                    "blocos": self._blocos(est, entrada, ctx_base),
                }, sufixo="")
                saidas[est.id] = saida
                final_texto = saida

            elif est.tipo == "paralelo":
                respostas = []
                for i in range(est.n):
                    respostas.append(self._chamada(est, messages, system_content, {
                        **ctx_base, "i": i + 1, "n": est.n,
                        "papel": self._papel(est, i),
                        "subtarefa": subtarefas[i] if subtarefas else task_content,
                        "resposta_anterior": self._texto(entrada),
                        "blocos": self._blocos(est, entrada, ctx_base),
                    }, sufixo=f"_{i + 1}"))
                saidas[est.id] = respostas

            elif est.tipo == "debate":
                atuais = list(entrada or [])
                for rodada in range(1, est.rodadas + 1):
                    refinadas = []
                    for i in range(est.n):
                        pares = "\n\n".join(
                            renderizar(est.formato_par, {
                                "j": j + 1,
                                "saida": atuais[j] if j < len(atuais) else "",
                                "subtarefa_j": subtarefas[j] if j < len(subtarefas) else "",
                            })
                            for j in range(est.n) if j != i
                        )
                        refinadas.append(self._chamada(est, messages, system_content, {
                            **ctx_base, "i": i + 1, "n": est.n, "rodada": rodada,
                            "papel": self._papel(est, i),
                            "subtarefa": subtarefas[i] if subtarefas else task_content,
                            "rodada_anterior": rodada - 1,
                            "resposta_anterior": atuais[i] if i < len(atuais) else "",
                            "pares": pares,
                        }, sufixo=f"_{i + 1}", extra={"rodada": rodada}))
                    atuais = refinadas
                saidas[est.id] = atuais

            else:  # reduzir
                saida = self._chamada(est, messages, system_content, {
                    **ctx_base, "i": 1, "n": 1,
                    "blocos": self._blocos(est, entrada, ctx_base),
                    "resposta_anterior": self._texto(entrada),
                }, sufixo="")
                saidas[est.id] = saida
                final_texto = saida

            if est.final:
                final_texto = self._texto(saidas[est.id])

        return final_texto

    # ── auxiliares ───────────────────────────────────────────────────────────

    def _chamada(
        self,
        est: Estagio,
        mensagens_originais: list[BaseMessage],
        system_content: str,
        contexto: dict[str, Any],
        sufixo: str,
        extra: dict | None = None,
    ) -> str:
        """Uma chamada ao LLM, com os dois traces que a instrumentação espera."""
        agente_id = f"{est.id}{sufixo}"
        meta = {"estagio": est.id, **(extra or {})}
        contexto = {**contexto, **self._saidas_nomeadas()}

        if est.entrada_bruta:
            # Repassa as mensagens exatamente como o harness as montou. É o que
            # torna sas/independent idênticos byte a byte às classes embutidas,
            # que chamam llm.invoke(messages) sem reconstruir nada.
            mensagens = mensagens_originais
            registrado = self._extract_human(mensagens_originais)
        else:
            sistema = renderizar(est.system, contexto) if est.system else system_content
            registrado = renderizar(est.prompt, contexto)
            mensagens = [SystemMessage(content=sistema), HumanMessage(content=registrado)]

        self.last_trace.append(AgentTrace(
            agent_id=agente_id, role="human", content=registrado,
            step=self._passo, metadata=meta,
        ))
        self._passo += 1

        resposta = self.llm.invoke(mensagens)
        saida = texto_da_resposta(resposta)

        meta_saida = {**meta, "usage": self._usage(resposta)}
        if est.final:
            meta_saida["is_final"] = True

        self.last_trace.append(AgentTrace(
            agent_id=agente_id, role="assistant", content=saida,
            step=self._passo, metadata=meta_saida,
        ))
        self._passo += 1
        return saida

    def _saidas_nomeadas(self) -> dict[str, str]:
        """{saida:<id>} — permite um estágio citar qualquer anterior pelo nome."""
        return {f"saida:{k}": self._texto(v) for k, v in self._saidas.items()}

    def _papel(self, est: Estagio, i: int) -> str:
        """Persona do agente i. Cicla se houver menos papéis que agentes."""
        return est.papeis[i % len(est.papeis)] if est.papeis else ""

    @staticmethod
    def _texto(valor: str | list[str] | None) -> str:
        if valor is None:
            return ""
        return valor if isinstance(valor, str) else "\n\n".join(valor)

    def _blocos(
        self,
        est: Estagio,
        entrada: str | list[str] | None,
        ctx_base: dict[str, Any] | None = None,
    ) -> str:
        """As respostas do estágio consumido, formatadas conforme a spec."""
        if entrada is None:
            return ""
        itens = [entrada] if isinstance(entrada, str) else list(entrada)
        base = ctx_base or {}
        # O rótulo do bloco pode citar o contexto — o hybrid escreve
        # "após {rodadas:debate} round(s)" no cabeçalho de cada worker.
        return "\n\n".join(
            renderizar(est.formato_bloco, {**base, "j": j + 1, "saida": s})
            for j, s in enumerate(itens)
        )
