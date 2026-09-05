"""
equivalencia.py — prova que as propostas iniciais reproduzem as classes embutidas.

Roda a mesma topologia pelos dois caminhos — a classe Python e a especificação
declarativa — com um LLM falso de roteiro fixo, e compara os prompts recebidos
byte a byte.

O que isto prova: que os quatro tipos de estágio bastam para expressar as cinco
arquiteturas de Kim et al. (2025).

O que isto NÃO prova: que o interpretador está correto para especificação
arbitrária. A igualdade vale em parte por construção — os prompts das propostas
foram transcritos do código das classes. Por isso há também um teste de
propriedade sobre especificações geradas ao acaso; e mesmo ele é cobertura, não
prova.

Custo: zero. Nenhuma chamada de rede.
"""
from __future__ import annotations

import random
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.agent_factory import create_agent
from src.agents.propostas_iniciais import PROPOSTAS_INICIAIS
from src.agents.topologia_spec import (
    EspecTopologia,
    chamadas_por_instancia,
    validar_topologia,
)


class _Resposta:
    """Imita o retorno do LangChain no que o pipeline consome."""

    def __init__(self, texto: str):
        self.content = texto
        self.usage_metadata = {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }


class LLMFalso:
    """
    LLM determinístico que grava tudo o que recebe.

    O roteiro importa: o primeiro item precisa ser uma decomposição numerada,
    senão parse_subtarefas cai no fallback e os dois lados divergiriam por um
    motivo alheio à especificação.
    """

    def __init__(self, roteiro: list[str] | None = None):
        self.roteiro = roteiro or []
        self.recebidos: list[list[Any]] = []
        self._i = 0

    def invoke(self, mensagens):
        # Guarda (papel, conteúdo) de cada mensagem — é o que define o prompt.
        self.recebidos.append([(type(m).__name__, m.content) for m in mensagens])
        if self._i < len(self.roteiro):
            texto = self.roteiro[self._i]
        else:
            texto = f"resposta-{self._i}"
        self._i += 1
        return _Resposta(texto)


ROTEIRO_PADRAO = [
    "1. Analisar o risco de crédito\n2. Avaliar a liquidez\n3. Concluir a recomendação",
    "resposta-a", "resposta-b", "resposta-c",
    "refino-a", "refino-b", "refino-c",
    "refino2-a", "refino2-b", "refino2-c",
    "sintese-final",
]

# Parâmetros com que cada classe embutida é construída para bater com a
# proposta correspondente. São os padrões das próprias classes.
KWARGS_EQUIVALENTES: dict[str, dict] = {
    "sas":           {},
    "independent":   {"n_agents": 3},
    "centralized":   {"n_workers": 3},
    "decentralized": {"n_agents": 3, "debate_rounds": 1},
    "hybrid":        {"n_workers": 3, "debate_rounds": 1},
}


def _mensagens_de_teste() -> list:
    return [
        SystemMessage(content="Você é um classificador preciso."),
        HumanMessage(content="Classifique: o cliente atrasou 90 dias.\n\nResponda com uma palavra."),
    ]


def comparar(nome: str) -> dict:
    """Roda os dois caminhos e devolve o diagnóstico da comparação."""
    msgs = _mensagens_de_teste()
    spec = PROPOSTAS_INICIAIS[nome]

    # Cada classe guarda o LLM sob um nome diferente (llm, worker_llm,
    # orchestrator_llm...), então seguramos a referência aqui em vez de
    # procurá-la no agente. Uma instância só grava todas as chamadas em ordem,
    # inclusive as do orquestrador — que é o mesmo objeto por padrão.
    falso_a = LLMFalso(list(ROTEIRO_PADRAO))
    falso_b = LLMFalso(list(ROTEIRO_PADRAO))

    embutido = create_agent(nome, llm=falso_a, **KWARGS_EQUIVALENTES[nome])
    declarativo = create_agent("declarativo", llm=falso_b, spec=spec)

    saida_a = embutido.run(msgs)
    saida_b = declarativo.run(msgs)

    prompts_a = falso_a.recebidos
    prompts_b = falso_b.recebidos

    esperado = chamadas_por_instancia(validar_topologia(spec))

    divergencia = None
    if len(prompts_a) != len(prompts_b):
        divergencia = f"nº de chamadas: classe={len(prompts_a)} spec={len(prompts_b)}"
    else:
        for i, (a, b) in enumerate(zip(prompts_a, prompts_b)):
            if a != b:
                divergencia = _primeira_diferenca(i, a, b)
                break

    # Os traces precisam contar tokens do mesmo jeito, senão o painel de custo
    # mostraria números diferentes para topologias equivalentes.
    usos_a = [t for t in embutido.trace_dicts() if t.get("usage")]
    usos_b = [t for t in declarativo.trace_dicts() if t.get("usage")]

    return {
        "nome": nome,
        "chamadas_classe": len(prompts_a),
        "chamadas_spec": len(prompts_b),
        "chamadas_estimadas": esperado,
        "steps_com_usage_classe": len(usos_a),
        "steps_com_usage_spec": len(usos_b),
        "saida_igual": saida_a == saida_b,
        "prompts_iguais": divergencia is None,
        "estimativa_confere": esperado == len(prompts_b),
        "divergencia": divergencia,
    }


def _primeira_diferenca(indice: int, a: list, b: list) -> str:
    if len(a) != len(b):
        return f"chamada {indice + 1}: nº de mensagens classe={len(a)} spec={len(b)}"
    for j, (ma, mb) in enumerate(zip(a, b)):
        if ma != mb:
            if ma[0] != mb[0]:
                return f"chamada {indice + 1}, msg {j + 1}: tipo {ma[0]} vs {mb[0]}"
            ca, cb = ma[1], mb[1]
            k = next((k for k in range(min(len(ca), len(cb))) if ca[k] != cb[k]),
                     min(len(ca), len(cb)))
            return (
                f"chamada {indice + 1}, msg {j + 1}, char {k}:\n"
                f"      classe: ...{ca[max(0, k - 40):k + 40]!r}\n"
                f"      spec  : ...{cb[max(0, k - 40):k + 40]!r}"
            )
    return f"chamada {indice + 1}: diferença não localizada"


def comparar_todas() -> list[dict]:
    return [comparar(nome) for nome in PROPOSTAS_INICIAIS]


# ─────────────────────────────────────────────────────────────────────────────
# Teste de propriedade — cobertura, não prova
# ─────────────────────────────────────────────────────────────────────────────

def _spec_aleatoria(rnd: random.Random) -> dict:
    estagios: list[dict] = []
    produz_lista = False

    n_est = rnd.randint(1, 4)
    for i in range(n_est):
        ultimo = i == n_est - 1
        if ultimo:
            tipo = "reduzir" if produz_lista else "unico"
        elif produz_lista:
            tipo = rnd.choice(["debate", "reduzir"])
        else:
            tipo = rnd.choice(["unico", "paralelo"])

        est: dict = {"id": f"e{i}", "tipo": tipo, "prompt": f"passo {i}: {{task_content}}"}
        if tipo in ("paralelo", "debate"):
            est["n"] = rnd.randint(2, 4)
        if tipo == "debate":
            est["rodadas"] = rnd.randint(1, 2)
        if tipo == "paralelo" and not produz_lista and rnd.random() < 0.5:
            est["dividir"] = True
        if ultimo:
            est["final"] = True
        estagios.append(est)
        produz_lista = tipo in ("paralelo", "debate")

    return {"nome": "aleatoria", "estagios": estagios}


def teste_de_propriedade(n: int = 100, semente: int = 42) -> dict:
    """Gera specs válidas ao acaso: nenhuma pode explodir, e a contagem tem de bater."""
    rnd = random.Random(semente)
    msgs = _mensagens_de_teste()
    testadas = falhas = 0
    erros: list[str] = []

    for _ in range(n):
        bruta = _spec_aleatoria(rnd)
        try:
            spec = validar_topologia(bruta)
        except Exception:
            continue  # combinação inválida — o gerador não é perfeito, tudo bem
        testadas += 1
        try:
            falso = LLMFalso()
            agente = create_agent("declarativo", llm=falso, spec=spec)
            agente.run(msgs)
            reais = len(falso.recebidos)
            estimadas = chamadas_por_instancia(spec)
            if reais != estimadas:
                falhas += 1
                erros.append(f"{[e.tipo for e in spec.estagios]}: reais={reais} estimadas={estimadas}")
        except Exception as e:
            falhas += 1
            erros.append(f"{[e2.tipo for e2 in spec.estagios]}: {type(e).__name__}: {e}")

    return {"testadas": testadas, "falhas": falhas, "erros": erros[:5]}
