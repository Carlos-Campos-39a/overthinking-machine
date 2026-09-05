"""
parse_subtarefas.py — leitura da decomposição produzida por um orquestrador.

O orquestrador recebe "responda com N subtarefas numeradas" e devolve texto
livre. Esta função extrai as N subtarefas dele, com degradação previsível
quando o modelo não obedece ao formato.

Estava duplicada, idêntica, em CentralizedMAS._parse_subtasks e
HybridMAS._parse_subtasks. Foi extraída para que o interpretador declarativo
use exatamente o mesmo parser das classes embutidas: se as três cópias
divergissem, o teste de equivalência quebraria por um motivo que não tem nada
a ver com a especificação sendo testada.
"""
from __future__ import annotations


def parse_subtarefas(bruto: str, fallback: str, n: int) -> list[str]:
    """
    Extrai n subtarefas de `bruto`.

    Ordem de tentativas:
      1. linhas que começam com dígito (o formato pedido ao orquestrador);
      2. parágrafos separados por linha em branco;
      3. `fallback` — a tarefa original, repetida.

    Sempre devolve exatamente n itens: completa com `fallback` se vieram menos,
    e corta se vieram mais. Um worker sem subtarefa receberia string vazia e
    responderia qualquer coisa, o que contaminaria a medição em silêncio.
    """
    linhas = [
        linha.strip()
        for linha in bruto.splitlines()
        if linha.strip() and linha.strip()[0].isdigit()
    ]
    subtarefas: list[str] = []
    for linha in linhas:
        limpa = linha.lstrip("0123456789.)- ").strip()
        if limpa:
            subtarefas.append(limpa)

    if not subtarefas:
        paragrafos = [p.strip() for p in bruto.split("\n\n") if p.strip()]
        subtarefas = paragrafos or [fallback]

    while len(subtarefas) < n:
        subtarefas.append(fallback)

    return subtarefas[:n]
