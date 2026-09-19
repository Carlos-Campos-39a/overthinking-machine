"""
testar_tarefas.py — verificação da linguagem de tarefas declarativas.

    python testar_tarefas.py
    python testar_tarefas.py --previa      # mostra a spec da triagem em JSON

CUSTO ZERO: nada aqui chama LLM.

Três camadas:

  1. EQUIVALÊNCIA — triagem_cobranca escrita como spec produz as mesmas
     instâncias, os mesmos PROMPTS (byte a byte) e os mesmos scores que a classe
     Python. É a prova de que a linguagem expressa uma tarefa que ninguém
     escreveu pensando nela.
  2. RECUSAS — cada limite e cada incoerência recusando com mensagem legível.
  3. AVISOS — o que não impede de rodar mas estraga a leitura do resultado
     (classes desbalanceadas, poucos casos, gabarito dentro do enunciado).
"""
from __future__ import annotations

import io
import json
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from src.tasks.equivalencia_tarefa import comparar_triagem, spec_da_triagem  # noqa: E402
from src.tasks.tarefa_declarativa import TarefaDeclarativa  # noqa: E402
from src.tasks.tarefa_spec import (  # noqa: E402
    MAX_CASOS, avisos_de_tarefa, erros_de_tarefa, resumo_da_tarefa, validar_tarefa,
)

_falhas = 0


def check(nome: str, ok: bool, detalhe: str = "") -> bool:
    global _falhas
    if not ok:
        _falhas += 1
    print(f"  [{'ok' if ok else 'XX'}] {nome}" + (f" — {detalhe}" if detalhe else ""))
    return ok


def secao(t: str) -> None:
    print(f"\n{t}\n" + "─" * 66)


def _base() -> dict:
    """Spec mínima e válida, para variar um campo por vez."""
    return {
        "nome": "tarefa-de-teste",
        "instrucao": "Classifique o caso.",
        "rotulos_validos": ["sim", "nao"],
        "casos": [
            {"id": "c1", "entrada": "caso um", "esperado": "sim"},
            {"id": "c2", "entrada": "caso dois", "esperado": "nao"},
        ],
    }


# ── 1. equivalência ──────────────────────────────────────────────────────────

def t_equivalencia() -> None:
    secao("1. EQUIVALÊNCIA — a spec reproduz a classe Python?")
    r = comparar_triagem()
    check("triagem_cobranca: instâncias, prompts e scores idênticos", r["igual"],
          f"{r['instancias']} instâncias · {r['prompts_conferidos']} prompts · "
          f"{r['scores_conferidos']} scores")
    for d in r["divergencias"]:
        print(f"       {d}")

    # A spec tem de sobreviver a uma ida e volta por JSON: é assim que ela viaja
    # da interface e do MCP até aqui.
    spec = spec_da_triagem()
    bruta = json.loads(spec.model_dump_json())
    revalidada = validar_tarefa(bruta)
    check("sobrevive a ida e volta por JSON",
          revalidada.model_dump() == spec.model_dump())

    t = TarefaDeclarativa(bruta, num_instances=5, seed=42)
    amostra = t.sample()
    check("amostragem determinística com a mesma semente",
          [i.id for i in amostra] == [i.id for i in TarefaDeclarativa(bruta, num_instances=5, seed=42).sample()],
          ", ".join(i.id for i in amostra))
    check("semente diferente muda a amostra",
          [i.id for i in amostra] != [i.id for i in TarefaDeclarativa(bruta, num_instances=5, seed=7).sample()])


# ── 2. recusas ───────────────────────────────────────────────────────────────

def t_recusas() -> None:
    secao("2. RECUSAS — cada limite fecha?")

    casos: list[tuple[str, dict, str]] = [
        ("campo desconhecido não entra",
         {**_base(), "executar": "os.system"}, "Extra inputs"),
        ("nome com maiúscula e espaço",
         {**_base(), "nome": "Minha Tarefa"}, "inválido"),
        ("um rótulo só em rotulos_validos",
         {**_base(), "rotulos_validos": ["sim"]}, "at least 2"),
        ("rótulos repetidos",
         {**_base(), "rotulos_validos": ["sim", "sim", "nao"]}, "repetidos"),
        ("caso espera rótulo fora da lista",
         {**_base(), "casos": [{"id": "c1", "entrada": "x", "esperado": "talvez"},
                               {"id": "c2", "entrada": "y", "esperado": "nao"}]},
         "não está em rotulos_validos"),
        ("ids de caso repetidos",
         {**_base(), "casos": [{"id": "c1", "entrada": "x", "esperado": "sim"},
                               {"id": "c1", "entrada": "y", "esperado": "nao"}]},
         "repetidos"),
        ("todos os casos com o mesmo gabarito",
         {**_base(), "casos": [{"id": "c1", "entrada": "x", "esperado": "sim"},
                               {"id": "c2", "entrada": "y", "esperado": "sim"}]},
         "não mede nada"),
        ("sem casos",
         {**_base(), "casos": []}, "at least 1"),
        ("acima do teto de casos",
         {**_base(), "casos": [{"id": f"c{i}", "entrada": f"caso {i}",
                                "esperado": "sim" if i else "nao"}
                               for i in range(MAX_CASOS + 1)]},
         f"o teto é {MAX_CASOS}"),
        ("caso longo demais",
         {**_base(), "casos": [{"id": "c1", "entrada": "x" * 5000, "esperado": "sim"},
                               {"id": "c2", "entrada": "y", "esperado": "nao"}]},
         "at most 4000"),
        ("exemplo usa rótulo inexistente",
         {**_base(), "exemplos": [{"entrada": "x", "saida": "talvez"}]},
         "não está em rotulos_validos"),
        ("tipo fora da lista fechada",
         {**_base(), "tipo": "qualquer_coisa"}, "Input should be"),
        ("spec não é objeto", "sou uma string", "objeto JSON"),
    ]

    for nome, spec, trecho in casos:
        errs = erros_de_tarefa(spec)
        texto = " | ".join(errs)
        check(nome, bool(errs) and trecho in texto, texto[:110] if errs else "ACEITOU")

    check("a spec mínima válida passa", not erros_de_tarefa(_base()))


# ── 3. avisos ────────────────────────────────────────────────────────────────

def t_avisos() -> None:
    secao("3. AVISOS — o que não impede de rodar, mas estraga a leitura")

    # 8 de 10 casos com o mesmo rótulo: responder sempre isso já tira 0.80.
    desbal = {**_base(), "casos": [{"id": f"c{i}", "entrada": f"caso {i}",
                                    "esperado": "sim" if i < 8 else "nao"}
                                   for i in range(10)]}
    spec = validar_tarefa(desbal)
    avisos = avisos_de_tarefa(spec)
    check("classes desbalanceadas geram aviso",
          any("desbalanceadas" in a for a in avisos),
          f"linha de base {spec.linha_de_base():.2f}")
    check("linha de base calculada certo", abs(spec.linha_de_base() - 0.8) < 1e-9)

    check("poucos casos geram aviso",
          any("caso(s)" in a for a in avisos_de_tarefa(validar_tarefa(_base()))))

    check("falta de exemplos gera aviso",
          any("few-shot" in a for a in avisos_de_tarefa(validar_tarefa(_base()))))

    vaza = {**_base(), "casos": [{"id": "c1", "entrada": "a resposta é sim", "esperado": "sim"},
                                 {"id": "c2", "entrada": "outro caso", "esperado": "nao"}]}
    check("gabarito dentro do enunciado gera aviso",
          any("dentro da própria entrada" in a for a in avisos_de_tarefa(validar_tarefa(vaza))))

    dup = {**_base(), "casos": [{"id": "c1", "entrada": "igual", "esperado": "sim"},
                                {"id": "c2", "entrada": "igual", "esperado": "nao"}]}
    check("entradas duplicadas geram aviso",
          any("entrada idêntica" in a for a in avisos_de_tarefa(validar_tarefa(dup))))

    check("a tarefa real da plataforma não dispara aviso nenhum",
          avisos_de_tarefa(spec_da_triagem()) == [],
          str(avisos_de_tarefa(spec_da_triagem())))


# ── 4. score ─────────────────────────────────────────────────────────────────

def t_score() -> None:
    secao("4. SCORE — acerto exato, sem crédito por ambiguidade")
    t = TarefaDeclarativa(_base())
    t.load()
    inst = t._instances[0]          # esperado: "sim"

    casos = [
        ("resposta exata", "sim", 1.0),
        ("com espaços", "  sim  ", 1.0),
        ("maiúscula", "SIM", 1.0),
        ("em frase", "a resposta é sim", 1.0),
        ("rótulo errado", "nao", 0.0),
        ("ambígua: os dois rótulos", "sim ou nao", 0.0),
        ("vazia", "", 0.0),
        ("None", None, 0.0),
        ("substring que não é o rótulo", "simples", 0.0),
    ]
    for nome, resposta, esperado in casos:
        obtido = t.score(resposta, inst)
        check(f"{nome} → {esperado}", obtido == esperado, f"deu {obtido}")


def main() -> int:
    if "--previa" in sys.argv:
        print(spec_da_triagem().model_dump_json(indent=2))
        return 0

    print("=" * 66)
    print("  testar_tarefas.py — linguagem declarativa de tarefas")
    print("=" * 66)
    t_equivalencia()
    t_recusas()
    t_avisos()
    t_score()
    print()
    print("=" * 66)
    print("  tudo passou" if not _falhas else f"  {_falhas} FALHA(S)")
    print("=" * 66)
    print(f"\nResumo da tarefa de referência:\n  "
          + json.dumps(resumo_da_tarefa(spec_da_triagem()), ensure_ascii=False)[:300])
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
