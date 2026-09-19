"""
testar_api.py — confere os contratos da API que ninguém mais confere.

    python testar_api.py

Roda a API em processo (TestClient), sem subir servidor. NÃO GASTA CHAMADA DE
MODELO: toda requisição aqui é recusada com HTTP 400 antes de qualquer execução,
ou é a simulação do módulo 2, que não chama modelo nenhum.

Duas famílias de checagem:

1. TETOS DE CUSTO. /api/benchmark e /api/prompt-sensitivity não tinham limite
   nenhum, e /api/run só limitava topologia declarativa — n_agents=5000 numa
   arquitetura embutida passava direto, com a chave do visitante pagando.

2. HONESTIDADE DO MÓDULO 2. A instância não lê ativações de modelo: o payload
   tem de dizer mode="simulacao" mesmo quando pedem "real", e a probe na camada 0
   tem de ficar perto do acaso. Se ela der ~1.0 na camada 0, a simulação voltou a
   vazar o rótulo (já aconteceu: o agente simulado acertava sse rótulo == 1).
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).parent
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

# Embrulha o stdout DEPOIS de importar o server: embrulhar antes fecha o buffer
# quando o módulo mexe no próprio stdout, e o processo morre sem imprimir nada.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

c = TestClient(server.app)
_falhas = 0


def check(nome: str, ok: bool, detalhe: str = "") -> bool:
    global _falhas
    if not ok:
        _falhas += 1
    print(f"  [{'ok' if ok else 'XX'}] {nome}" + (f" — {detalhe}" if detalhe else ""))
    return ok


def recusa(nome: str, rota: str, corpo: dict, trecho: str) -> None:
    r = c.post(rota, json=corpo)
    detalhe = r.text[:110].replace("\n", " ")
    check(nome, r.status_code == 400 and trecho in r.text, f"HTTP {r.status_code} · {detalhe}")


def tetos() -> None:
    print("\n1. TETOS DE CUSTO")
    modelos = lambda n: [f"google/m{i}" for i in range(n)]  # noqa: E731

    recusa("benchmark: 13 modelos", "/api/benchmark", {"models": modelos(13)}, "teto")
    recusa("benchmark: reps=9", "/api/benchmark", {"models": ["google/x"], "reps": 9}, "reps")
    recusa("benchmark: 51 instâncias", "/api/benchmark",
           {"models": ["google/x"], "num_instances": 51}, "teto")
    recusa("benchmark: lote acima do teto", "/api/benchmark",
           {"models": modelos(10), "reps": 5, "num_instances": 50, "architecture": "hybrid"}, "cabem")
    recusa("benchmark: n_agents=5000", "/api/benchmark",
           {"models": ["google/x"], "architecture": "independent", "agent_kwargs": {"n_agents": 5000}},
           "por instância")
    recusa("benchmark: agent_kwargs não numérico", "/api/benchmark",
           {"models": ["google/x"], "architecture": "independent", "agent_kwargs": {"n_agents": "muitos"}},
           "inteiros")

    prompt = ". ".join(f"Regra numero {i} do prompt de sistema" for i in range(12)) + "."
    recusa("sensibilidade: lote acima do teto", "/api/prompt-sensitivity",
           {"system_prompt": prompt, "num_instances": 50, "reps": 5, "architecture": "hybrid"}, "teto")
    recusa("sensibilidade: max_pairs=99", "/api/prompt-sensitivity",
           {"system_prompt": prompt, "max_pairs": 99}, "max_pairs")

    base = {"model": "google/x", "harness": "zero_shot", "task": "text_classification", "evaluator": "binary"}
    recusa("run: n_agents=500 (embutida)", "/api/run",
           {**base, "architecture": "independent", "agent_kwargs": {"n_agents": 500}}, "por instância")
    recusa("run: meta_budget=99", "/api/run", {**base, "architecture": "sas", "meta_budget": 99}, "meta_budget")
    recusa("run: decentralized x 50 instâncias", "/api/run",
           {**base, "architecture": "decentralized", "num_instances": 50,
            "agent_kwargs": {"n_agents": 5, "debate_rounds": 3}}, "Cabem")

    lim = c.get("/api/limites").json()["limites"]
    for k in ("max_modelos_por_lote", "max_reps", "max_chamadas_por_lote"):
        check(f"/api/limites publica {k}", k in lim, str(lim.get(k)))


def _rodar_modulo2(corpo: dict) -> tuple[dict | None, list[str]]:
    final, logs = None, []
    with c.stream("POST", "/api/geometry/run", json=corpo) as r:
        for linha in r.iter_lines():
            if not linha.startswith("data:"):
                continue
            evt = json.loads(linha[5:].strip())
            if evt["type"] == "done":
                final = evt["results"]
            elif evt["type"] == "log":
                logs.append(evt.get("text", ""))
    return final, logs


def modulo2() -> None:
    print("\n2. HONESTIDADE DO MÓDULO 2")
    for modo in ("simulate", "real"):
        final, logs = _rodar_modulo2({"dataset": "cities", "arch": "sas_zero_shot",
                                      "n_instances": 60, "mode": modo})
        if not check(f"mode={modo}: terminou", final is not None):
            continue
        check(f"mode={modo}: payload diz simulacao", final.get("mode") == "simulacao"
              and final.get("sintetico") is True, f"mode={final.get('mode')}")
        check(f"mode={modo}: probe declara validação cruzada", "cruzada" in final.get("probe_metodo", ""))
        if modo == "real":
            check("mode=real: o log avisa que não é hook real",
                  any("não lê ativações reais" in t for t in logs))

        curva = final["probe_accuracies"]
        base = final["probe_baseline"]
        n, ok = final["n_instances"], final["n_correct"]
        # Acerto independente do rótulo: a acurácia do agente fica perto da
        # anunciada (~0.75), não dos 0.50 que o vazamento de rótulo produzia.
        check(f"mode={modo}: agente simulado acerta ~75%", 0.60 <= ok / n <= 0.90, f"{ok}/{n}")
        # Camadas iniciais sem sinal: a probe não pode bater a linha de base com folga.
        inicio = sum(curva[:3]) / 3
        check(f"mode={modo}: camadas 0-2 perto do acaso", inicio <= base + 0.10,
              f"média {inicio:.2f} · linha de base {base:.2f}")
        check(f"mode={modo}: camadas finais separam", min(curva[-4:]) >= 0.90, f"mín {min(curva[-4:]):.2f}")


def tarefa_declarativa() -> None:
    print("\n3. TAREFA DECLARATIVA")
    from src.tasks.equivalencia_tarefa import spec_da_triagem

    spec = json.loads(spec_da_triagem().model_dump_json())

    cat = c.get("/api/tarefas").json()
    por_nome = {t["nome"]: t for t in cat["tarefas"]}
    check("catálogo lista as tarefas embutidas", "triagem_cobranca" in por_nome,
          ", ".join(sorted(por_nome)))
    tri = por_nome.get("triagem_cobranca", {})
    # Sem a linha de base, 0.80 parece bom mesmo quando o chute fixo dá 0.78.
    check("catálogo traz a linha de base", tri.get("linha_de_base") == 0.25,
          str(tri.get("linha_de_base")))
    check("catálogo traz casos e rótulos",
          tri.get("casos") == 24 and len(tri.get("rotulos") or []) == 6,
          f"{tri.get('casos')} casos, {len(tri.get('rotulos') or [])} rótulos")
    # Tarefa de resposta aberta não tem rótulo fechado: contar frequência de
    # parágrafos daria uma "distribuição" de classes de tamanho 1 e uma linha de
    # base de 1/n — número sem significado num catálogo lido por agentes.
    fin = por_nome.get("finance_agent", {})
    check("tarefa de prosa não inventa linha de base",
          fin.get("linha_de_base") is None and "distribuicao" not in fin,
          f"linha_de_base={fin.get('linha_de_base')} · nota={str(fin.get('nota'))[:60]}")

    v = c.post("/api/tarefas/validar", json={"spec": spec}).json()
    check("valida a spec de referência", v.get("ok") and not v.get("erros"), str(v.get("erros")))
    check("resumo sem avisos para uma tarefa boa", v["resumo"]["avisos"] == [],
          str(v["resumo"]["avisos"]))

    # Aceita, mas avisa: desbalanceamento não é erro, é armadilha de leitura.
    desbal = {**spec, "casos": [dict(cc, esperado="operador") if i > 3 else cc
                                for i, cc in enumerate(spec["casos"])]}
    v2 = c.post("/api/tarefas/validar", json={"spec": desbal}).json()
    check("tarefa desbalanceada: aceita com aviso",
          v2.get("ok") and any("desbalanceadas" in a for a in v2["resumo"]["avisos"]),
          str(v2.get("resumo", {}).get("avisos"))[:100])

    base = {"model": "google/x", "architecture": "sas", "harness": "zero_shot",
            "task": "text_classification", "evaluator": "binary"}
    recusa("run: tarefa com campo desconhecido", "/api/run",
           {**base, "tarefa_spec": {**spec, "executar": "x"}}, "tarefa inválida")
    recusa("run: mais instâncias do que casos", "/api/run",
           {**base, "tarefa_spec": spec, "num_instances": 40}, "24 caso")
    recusa("benchmark: tarefa inválida", "/api/benchmark",
           {"models": ["google/x"], "tarefa_spec": {**spec, "executar": "x"}}, "tarefa inválida")
    recusa("sensibilidade: tarefa inválida", "/api/prompt-sensitivity",
           {"system_prompt": "Regra um. Regra dois. Regra três.",
            "tarefa_spec": {**spec, "executar": "x"}}, "tarefa inválida")

    lim = c.get("/api/limites").json()["limites"]
    check("/api/limites publica os tetos de tarefa",
          "max_casos" in lim and "max_chars_caso" in lim, f"max_casos={lim.get('max_casos')}")


def configuracao() -> None:
    print("\n4. CONFIGURAÇÃO VISÍVEL DE FORA")
    h = c.get("/api/health").json()
    s = c.get("/api/biblioteca/saude").json()

    # Sem isto não há como conferir se OTM_ADMIN_TOKEN pegou: uma requisição com
    # token errado e uma instância sem token nenhum devolvem o mesmo 403.
    esperado = bool(os.getenv("OTM_ADMIN_TOKEN"))
    check("/api/health diz se o admin está configurado",
          h.get("admin_configurado") is esperado, f"admin_configurado={h.get('admin_configurado')}")
    check("a saúde da biblioteca concorda",
          s.get("admin_configurado") is esperado)

    # Booleano, nunca o valor.
    valor = os.getenv("OTM_ADMIN_TOKEN") or ""
    check("o valor do token nunca aparece na resposta",
          not valor or valor not in (json.dumps(h) + json.dumps(s)))

    # As duas rotas não podem se contradizer: "persistente" respondia True só
    # por existir arquivo em disco, mesmo num contêiner sem volume.
    check("health e biblioteca/saude concordam sobre persistência",
          h.get("biblioteca_persistente") == s.get("persistente"),
          f"health={h.get('biblioteca_persistente')} saude={s.get('persistente')}")
    check("sem volume, a saúde avisa em vez de dizer só 'true'",
          bool(s.get("volume_configurado")) or "recriado a cada deploy" in str(s.get("aviso", "")),
          str(s.get("aviso"))[:70])


def main() -> int:
    print("=" * 66)
    print("  testar_api.py — tetos de custo e honestidade do módulo 2")
    print("=" * 66)
    tetos()
    modulo2()
    tarefa_declarativa()
    configuracao()
    print("\n" + ("tudo passou" if not _falhas else f"{_falhas} FALHA(S)"))
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
