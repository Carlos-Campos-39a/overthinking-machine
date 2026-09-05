"""
agent_factory.py — Factory de arquiteturas de agentes.

Instancia a arquitetura correta a partir do nome no config.yaml.
Único ponto de acoplamento: todo o resto do código é agnóstico à arquitetura.

Arquiteturas disponíveis (Kim et al., 2025):
    sas           → SingleAgentSystem   (baseline, 1 LLM, 0 overhead)
    independent   → IndependentMAS      (n agentes, sem peer communication)
    centralized   → CentralizedMAS      (orquestrador hierárquico + workers)
    decentralized → DecentralizedMAS    (peer-to-peer debate)
    hybrid        → HybridMAS           (hierarquia + peer debate)
"""
from __future__ import annotations
from typing import Any
from langchain_core.language_models import BaseChatModel

from src.agents.agent_base import AgentBase
from src.agents.sas import SingleAgentSystem
from src.agents.independent import IndependentMAS
from src.agents.centralized import CentralizedMAS
from src.agents.decentralized import DecentralizedMAS
from src.agents.hybrid import HybridMAS
from src.agents.agente_declarativo import AgenteDeclarativo


# Mapa: nome → classe
_AGENT_CLASSES: dict[str, type[AgentBase]] = {
    "sas":           SingleAgentSystem,
    "independent":   IndependentMAS,
    "centralized":   CentralizedMAS,
    "decentralized": DecentralizedMAS,
    "hybrid":        HybridMAS,
    # Interpretador de topologias declarativas. Não aparece como card no
    # catálogo (interno=True em descrever_arquiteturas): é o motor por trás de
    # qualquer topologia montada pelo usuário, e recebe a spec via agent_kwargs.
    "declarativo":   AgenteDeclarativo,
}


def create_agent(
    architecture: str,
    llm: BaseChatModel,
    **kwargs: Any,
) -> AgentBase:
    """
    Instancia a arquitetura pelo nome.

    Args:
        architecture: nome da arquitetura (ex: "sas", "centralized")
        llm: modelo base a ser usado pelos agentes
        **kwargs: parâmetros extras passados ao construtor da arquitetura
                  ex: n_workers=3, debate_rounds=2, n_agents=4

    Returns:
        Instância de AgentBase pronta para uso.

    Raises:
        KeyError: se o nome da arquitetura não for reconhecido.
    """
    architecture = architecture.lower().strip()
    if architecture not in _AGENT_CLASSES:
        raise KeyError(
            f"Arquitetura '{architecture}' não encontrada. "
            f"Disponíveis: {list_architectures()}"
        )
    cls = _AGENT_CLASSES[architecture]
    return cls(llm=llm, **kwargs)


def list_architectures() -> list[str]:
    """Retorna lista de arquiteturas disponíveis."""
    return sorted(_AGENT_CLASSES.keys())


# Metadados das arquiteturas, servidos em GET /api/arquiteturas. Existe para que
# frontend e MCP parem de repetir a lista à mão — foi assim que o módulo 4
# passou a oferecer 3 harnesses e o MCP congelou 5 arquiteturas.
_DESCRICOES = {
    "sas":           ("Single Agent System", "Um LLM com o contexto completo. Baseline.", "O(k)"),
    "independent":   ("Independent MAS", "N agentes sem comunicação + agregador.", "O(nk)"),
    "centralized":   ("Centralized MAS", "Orquestrador decompõe, workers executam, orquestrador sintetiza.", "O(rnk)"),
    "decentralized": ("Decentralized MAS", "N pares debatem por r rodadas e consolidam.", "O(dnk)"),
    "hybrid":        ("Hybrid MAS", "Hierarquia com debate entre workers.", "O(rnk + pn)"),
    "declarativo":   ("Topologia declarativa", "Interpretador de topologias definidas por especificação.", "varia"),
}

_PARAMETROS = {
    "independent":   {"n_agents": 3},
    "centralized":   {"n_workers": 3},
    "decentralized": {"n_agents": 3, "debate_rounds": 1},
    "hybrid":        {"n_workers": 3, "debate_rounds": 1},
}


def descrever_arquiteturas() -> list[dict]:
    saida = []
    for nome in list_architectures():
        titulo, descricao, complexidade = _DESCRICOES.get(nome, (nome, "", ""))
        saida.append({
            "nome": nome,
            "titulo": titulo,
            "descricao": descricao,
            "complexidade": complexidade,
            "parametros": _PARAMETROS.get(nome, {}),
            # O declarativo é o motor por trás das topologias do usuário, não
            # uma opção de catálogo: a interface o esconde da grade de cards.
            "interno": nome == "declarativo",
        })
    return saida
