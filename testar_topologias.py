"""
testar_topologias.py — verifica a linguagem declarativa de topologias.

    python testar_topologias.py                    # roda tudo (custo zero)
    python testar_topologias.py --previa hybrid    # mostra os prompts de uma proposta
    python testar_topologias.py --previa minha.json
    python testar_topologias.py --validar minha.json

NENHUM MODO AQUI GASTA CHAMADA DE API. A prévia usa um LLM falso: ela mostra
exatamente os prompts que SERIAM enviados, o que também é o jeito de ler uma
topologia de terceiro antes de gastar a própria chave nela.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# O console do Windows usa cp1252 e quebra em qualquer acento.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

VERDE, VERM, AMAR, DIM, FIM = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"
OK, XX = f"{VERDE}ok{FIM}", f"{VERM}FALHOU{FIM}"

_falhas = 0


def secao(titulo: str) -> None:
    print(f"\n{titulo}")
    print("─" * 70)


def check(nome: str, passou: bool, detalhe: str = "") -> None:
    global _falhas
    if not passou:
        _falhas += 1
    print(f"  [{OK if passou else XX}] {nome}" + (f"  {DIM}{detalhe}{FIM}" if detalhe else ""))


# ─────────────────────────────────────────────────────────────────────────────

def teste_equivalencia() -> None:
    secao("1. EQUIVALÊNCIA — a especificação reproduz a classe embutida?")
    from src.agents.equivalencia import comparar_todas

    print(f"  {DIM}Roda cada topologia pelos dois caminhos com um LLM falso e compara")
    print(f"  os prompts recebidos byte a byte.{FIM}\n")

    for r in comparar_todas():
        passou = r["prompts_iguais"] and r["saida_igual"] and r["estimativa_confere"]
        check(
            f"{r['nome']:14s} {r['chamadas_classe']:2d} chamadas, prompts idênticos",
            passou,
            "" if passou else "",
        )
        if r["divergencia"]:
            print(f"        {VERM}{r['divergencia']}{FIM}")


def teste_limites() -> None:
    secao("2. LIMITES — cada teto realmente recusa?")
    from src.agents.topologia_spec import erros_de

    N = "teste"
    validas = {
        "topologia mínima": {"nome": N, "estagios": [
            {"id": "a", "tipo": "unico", "prompt": "x", "final": True}]},
        "pipeline completo": {"nome": N, "estagios": [
            {"id": "p", "tipo": "paralelo", "n": 3, "prompt": "x"},
            {"id": "d", "tipo": "debate", "n": 3, "rodadas": 2, "prompt": "y"},
            {"id": "r", "tipo": "reduzir", "prompt": "z", "final": True}]},
    }
    invalidas = {
        "9 estágios (teto 8)": {"nome": N, "estagios": [
            {"id": f"e{i}", "tipo": "unico", "prompt": "x", "final": i == 0} for i in range(9)]},
        "n=9 (teto 8)": {"nome": N, "estagios": [
            {"id": "p", "tipo": "paralelo", "n": 9, "prompt": "x"},
            {"id": "r", "tipo": "reduzir", "prompt": "y", "final": True}]},
        "rodadas=4 (teto 3)": {"nome": N, "estagios": [
            {"id": "p", "tipo": "paralelo", "n": 2, "prompt": "x"},
            {"id": "d", "tipo": "debate", "n": 2, "rodadas": 4, "prompt": "y"},
            {"id": "r", "tipo": "reduzir", "prompt": "z", "final": True}]},
        "57 chamadas (teto 40)": {"nome": N, "estagios": [
            {"id": "p", "tipo": "paralelo", "n": 8, "prompt": "x"},
            {"id": "d1", "tipo": "debate", "n": 8, "rodadas": 3, "prompt": "y"},
            {"id": "d2", "tipo": "debate", "n": 8, "rodadas": 3, "prompt": "y"},
            {"id": "r", "tipo": "reduzir", "prompt": "z", "final": True}]},
        "campo desconhecido": {"nome": N, "estagios": [
            {"id": "a", "tipo": "unico", "prompt": "x", "final": True, "injetado": 1}]},
        "referência para frente": {"nome": N, "estagios": [
            {"id": "a", "tipo": "unico", "de": "b", "prompt": "x", "final": True},
            {"id": "b", "tipo": "unico", "prompt": "y"}]},
        "dois estágios finais": {"nome": N, "estagios": [
            {"id": "a", "tipo": "unico", "prompt": "x", "final": True},
            {"id": "b", "tipo": "unico", "prompt": "y", "final": True}]},
        "nenhum final": {"nome": N, "estagios": [
            {"id": "a", "tipo": "unico", "prompt": "x"}]},
        "reduzir sem lista antes": {"nome": N, "estagios": [
            {"id": "a", "tipo": "unico", "prompt": "x"},
            {"id": "r", "tipo": "reduzir", "prompt": "y", "final": True}]},
        "prompt de 5000 chars": {"nome": N, "estagios": [
            {"id": "a", "tipo": "unico", "prompt": "y" * 5000, "final": True}]},
    }

    for nome, spec in validas.items():
        errs = erros_de(spec)
        check(f"aceita: {nome}", not errs, errs[0][:50] if errs else "")
    for nome, spec in invalidas.items():
        errs = erros_de(spec)
        check(f"recusa: {nome}", bool(errs), errs[0][:52] if errs else "ACEITOU — não deveria")


def teste_seguranca() -> None:
    secao("3. SEGURANÇA — template não vira execução de código")
    from src.agents.topologia_spec import renderizar

    # str.format() permitiria travessia de atributo aqui. A substituição por
    # lista branca deixa a chave literal.
    travessia = renderizar("{0.__class__.__mro__}", {})
    check("travessia de atributo fica literal", travessia == "{0.__class__.__mro__}", travessia[:40])

    json_literal = renderizar('responda {"nota": 1}', {})
    check("chave de JSON não quebra o prompt", json_literal == 'responda {"nota": 1}')

    desconhecida = renderizar("{nao_existe}", {})
    check("placeholder desconhecido não estoura", desconhecida == "{nao_existe}")

    subst = renderizar("faça {task_content}", {"task_content": "X"})
    check("placeholder conhecido é substituído", subst == "faça X")


def teste_propriedade() -> None:
    secao("4. PROPRIEDADE — especificações geradas ao acaso")
    from src.agents.equivalencia import teste_de_propriedade

    print(f"  {DIM}Cobertura, não prova: gera topologias válidas ao acaso e exige que")
    print(f"  nenhuma exploda e que a contagem real bata com a estimada.{FIM}\n")
    r = teste_de_propriedade(200)
    check(f"{r['testadas']} especificações aleatórias executam sem erro", r["falhas"] == 0)
    for e in r["erros"]:
        print(f"        {VERM}{e}{FIM}")


# ─────────────────────────────────────────────────────────────────────────────

def _carregar(alvo: str) -> dict:
    from src.agents.propostas_iniciais import PROPOSTAS_INICIAIS
    if alvo in PROPOSTAS_INICIAIS:
        return PROPOSTAS_INICIAIS[alvo]
    caminho = Path(alvo)
    if not caminho.exists():
        print(f"{VERM}Não encontrei '{alvo}'.{FIM}")
        print(f"Propostas disponíveis: {', '.join(PROPOSTAS_INICIAIS)}")
        sys.exit(1)
    return json.loads(caminho.read_text(encoding="utf-8"))


def modo_validar(alvo: str) -> None:
    from src.agents.topologia_spec import chamadas_por_instancia, erros_de, validar_topologia

    spec = _carregar(alvo)
    errs = erros_de(spec)
    if errs:
        print(f"\n{VERM}Especificação inválida:{FIM}")
        for e in errs:
            print(f"  · {e}")
        sys.exit(1)

    modelo = validar_topologia(spec)
    n = chamadas_por_instancia(modelo)
    print(f"\n{VERDE}Válida.{FIM}  {modelo.titulo or modelo.nome}")
    print(f"  estágios              : {len(modelo.estagios)}")
    print(f"  chamadas por instância: {n}")
    for e in modelo.estagios:
        marca = " ← final" if e.final else ""
        det = f"n={e.n}" if e.tipo in ("paralelo", "debate") else ""
        det += f" rodadas={e.rodadas}" if e.tipo == "debate" else ""
        print(f"    {e.tipo:9s} {e.id:14s} {e.chamadas():2d} chamada(s)  {DIM}{det}{FIM}{marca}")
    print(f"\n  {DIM}Custo com 10 instâncias: {n * 10} chamadas ao modelo.{FIM}")


def modo_previa(alvo: str) -> None:
    """Mostra os prompts que seriam enviados. Zero chamadas reais."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from src.agents.agent_factory import create_agent
    from src.agents.equivalencia import LLMFalso, ROTEIRO_PADRAO
    from src.agents.topologia_spec import chamadas_por_instancia, erros_de, validar_topologia

    spec = _carregar(alvo)
    errs = erros_de(spec)
    if errs:
        print(f"\n{VERM}Especificação inválida:{FIM}")
        for e in errs:
            print(f"  · {e}")
        sys.exit(1)

    modelo = validar_topologia(spec)
    msgs = [
        SystemMessage(content="Você é um classificador preciso."),
        HumanMessage(content="Classifique o risco: o cliente atrasou 90 dias.\n\nResponda com uma palavra."),
    ]

    falso = LLMFalso(list(ROTEIRO_PADRAO))
    agente = create_agent("declarativo", llm=falso, spec=modelo)
    agente.run(msgs)

    print(f"\n{AMAR}PRÉVIA — {modelo.titulo or modelo.nome}{FIM}")
    print(f"{DIM}Estes são os prompts que seriam enviados ao modelo. Nenhuma chamada")
    print(f"real foi feita; as respostas abaixo são de um LLM falso.{FIM}")
    print(f"\n{len(falso.recebidos)} chamadas (estimativa: {chamadas_por_instancia(modelo)})")

    for i, chamada in enumerate(falso.recebidos, 1):
        trace = [t for t in agente.trace_dicts() if t["role"] == "human"]
        estagio = trace[i - 1].get("estagio", "?") if i <= len(trace) else "?"
        print(f"\n{'═' * 70}")
        print(f"CHAMADA {i}/{len(falso.recebidos)}  ·  estágio: {estagio}")
        print("═" * 70)
        for papel, conteudo in chamada:
            rotulo = "system" if "System" in papel else "human"
            print(f"{DIM}── {rotulo} {'─' * (66 - len(rotulo))}{FIM}")
            texto = conteudo if len(conteudo) < 700 else conteudo[:700] + f"\n{DIM}[...]{FIM}"
            print(texto)


def main() -> None:
    args = sys.argv[1:]

    if "--previa" in args:
        modo_previa(args[args.index("--previa") + 1])
        return
    if "--validar" in args:
        modo_validar(args[args.index("--validar") + 1])
        return

    print("\n" + "═" * 70)
    print("  TOPOLOGIAS DECLARATIVAS — verificação (custo zero)")
    print("═" * 70)

    teste_equivalencia()
    teste_limites()
    teste_seguranca()
    teste_propriedade()

    print("\n" + "═" * 70)
    if _falhas:
        print(f"  {VERM}{_falhas} verificação(ões) falharam{FIM}")
    else:
        print(f"  {VERDE}tudo passou{FIM}")
    print("═" * 70)
    print(f"\n{DIM}Para ver os prompts de uma topologia:")
    print(f"  python testar_topologias.py --previa centralized{FIM}\n")
    sys.exit(1 if _falhas else 0)


if __name__ == "__main__":
    main()
