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


# Mapa: nome → classe
_AGENT_CLASSES: dict[str, type[AgentBase]] = {
    "sas":           SingleAgentSystem,
    "independent":   IndependentMAS,
    "centralized":   CentralizedMAS,
    "decentralized": DecentralizedMAS,
    "hybrid":        HybridMAS,
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
