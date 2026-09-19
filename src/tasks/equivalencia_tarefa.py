"""
equivalencia_tarefa.py — a spec declarativa reproduz a tarefa em Python?

Mesma ideia da equivalência de topologias: a linguagem nova só vale se conseguir
expressar o que já existe SEM diferença. Aqui a comparação é em três níveis, do
mais fraco ao mais forte:

  1. as instâncias (enunciado, gabarito, rótulos, exemplos)
  2. os PROMPTS que o harness monta a partir delas — byte a byte
  3. o score, sobre uma bateria de respostas difíceis

O nível 3 é o que mais importa e é onde eu quase errei: duas implementações de
"acerto exato" divergem em respostas ambíguas ("digital ou operador"), e é
justamente nelas que um modelo real cai.

Custo zero: nada aqui chama LLM.
"""
from __future__ import annotations

from src.harnesses.manual_harnesses import FewShotHarness, ZeroShotHarness
from src.tasks.tarefa_declarativa import TarefaDeclarativa
from src.tasks.tarefa_spec import EspecTarefa, validar_tarefa
from src.tasks.triagem_cobranca import (
    _INSTANCIAS, POLITICA, ROTULOS_VALIDOS, TriagemCobranca, _caso,
)

# Os mesmos exemplos que a classe embutida injeta no metadata.
_EXEMPLOS = [
    {"entrada": "saldo R$ 120,00 / atraso 40 dias / score 500 / sem acordo",
     "saida": "digital"},
    {"entrada": "saldo R$ 9.000,00 / atraso 150 dias / score 400 / promessa quebrada há 7 dias",
     "saida": "juridico"},
]


def spec_da_triagem() -> EspecTarefa:
    """
    triagem_cobranca escrita como especificação.

    Gerada da MESMA fonte que a classe (_INSTANCIAS e POLITICA), e não copiada à
    mão: uma transcrição manual provaria só que eu sei copiar. A prova de
    expressividade é a estrutura — instrução comum + casos + rótulos — dar conta
    de uma tarefa que ninguém escreveu pensando nesse formato.
    """
    return validar_tarefa({
        "nome": "triagem_cobranca",
        "titulo": "Triagem de cobrança",
        "descricao": "Aplicar uma política com precedência a casos de cobrança "
                     "com sinal conflitante.",
        "instrucao": POLITICA,
        "tipo": "classification",
        "formato_resposta": "single_label",
        "criterios": ["accuracy", "policy_precedence"],
        "rotulos_validos": list(ROTULOS_VALIDOS),
        "exemplos": _EXEMPLOS,
        "casos": [
            {
                "id": r["id"],
                # A entrada do caso é o enunciado SEM a política: a política é a
                # instrucao, comum a todos. Reconstruímos pelo mesmo _caso() que
                # a classe usa e removemos o prefixo — assim qualquer mudança de
                # formatação lá aparece aqui como divergência, e não passa batida.
                "entrada": _caso(saldo=r["saldo"], atraso=r["atraso"], score=r["score"],
                                 acordo=r["acordo"], promessa=r["promessa"],
                                 obs=r["obs"])[len(POLITICA):].lstrip("\n"),
                "esperado": r["gt"],
                "nota": r["nota"][:300],
            }
            for r in _INSTANCIAS
        ],
    })


# Respostas escolhidas para separar implementações de "acerto exato" que parecem
# iguais. As ambíguas são o ponto: um modelo real responde assim o tempo todo.
_RESPOSTAS_DE_PROVA = [
    "digital",
    "DIGITAL",
    "  digital  ",
    "operador",
    "manter_acordo",
    "baixa_contabil",
    "juridico",
    "suspender",
    "A resposta é digital.",
    "digital ou operador",             # ambígua: dois rótulos válidos
    "não é digital, é operador",       # ambígua, ainda que a intenção seja clara
    "acho que seria juridico, mas poderia ser operador",
    "digitalizar",                     # contém 'digital' sem ser o rótulo
    "",
    "nenhuma das anteriores",
    "Resposta: baixa_contabil (atraso > 720 dias)",
]


def _campos_comparaveis(inst) -> dict:
    """O que de fato afeta o experimento. Notas de análise ficam de fora."""
    return {
        "id": inst.id,
        "input": inst.input,
        "ground_truth": inst.ground_truth,
        "task_type": inst.task_type,
        "response_format": inst.response_format,
        "eval_criteria": list(inst.eval_criteria),
        "valid_labels": list(inst.metadata.get("valid_labels") or []),
        "examples": list(inst.metadata.get("examples") or []),
    }


def _mensagens(harness, inst) -> list[tuple[str, str]]:
    saida = harness.build_messages(inst)
    return [(type(m).__name__, m.content) for m in saida.messages]


def comparar_triagem() -> dict:
    """Roda os dois caminhos e devolve o diagnóstico."""
    embutida = TriagemCobranca(num_instances=len(_INSTANCIAS), seed=42)
    embutida.load()
    declarativa = TarefaDeclarativa(spec_da_triagem(),
                                    num_instances=len(_INSTANCIAS), seed=42)
    declarativa.load()

    a, b = embutida._instances, declarativa._instances
    divergencias: list[str] = []

    if len(a) != len(b):
        divergencias.append(f"nº de instâncias: classe={len(a)} spec={len(b)}")

    # ── 1. instâncias ────────────────────────────────────────────────────────
    for ia, ib in zip(a, b):
        ca, cb = _campos_comparaveis(ia), _campos_comparaveis(ib)
        for campo in ca:
            if ca[campo] != cb[campo]:
                va, vb = str(ca[campo]), str(cb[campo])
                k = next((k for k in range(min(len(va), len(vb))) if va[k] != vb[k]),
                         min(len(va), len(vb)))
                divergencias.append(
                    f"{ia.id}.{campo} difere no char {k}:\n"
                    f"      classe: ...{va[max(0, k - 40):k + 40]!r}\n"
                    f"      spec  : ...{vb[max(0, k - 40):k + 40]!r}"
                )
                break

    # ── 2. prompts, byte a byte ──────────────────────────────────────────────
    prompts_conferidos = 0
    for harness in (ZeroShotHarness(), FewShotHarness()):
        for ia, ib in zip(a, b):
            ma, mb = _mensagens(harness, ia), _mensagens(harness, ib)
            prompts_conferidos += 1
            if ma != mb:
                divergencias.append(
                    f"{harness.name} / {ia.id}: prompts diferem\n"
                    f"      classe: {ma!r:.300}\n"
                    f"      spec  : {mb!r:.300}"
                )
                break

    # ── 3. score ─────────────────────────────────────────────────────────────
    scores_conferidos = 0
    for ia, ib in zip(a, b):
        for resposta in _RESPOSTAS_DE_PROVA:
            sa = embutida.score(resposta, ia)
            sb = declarativa.score(resposta, ib)
            scores_conferidos += 1
            if sa != sb:
                divergencias.append(
                    f"{ia.id} · resposta {resposta!r}: classe={sa} spec={sb}"
                )

    return {
        "nome": "triagem_cobranca",
        "igual": not divergencias,
        "instancias": len(a),
        "prompts_conferidos": prompts_conferidos,
        "scores_conferidos": scores_conferidos,
        "divergencias": divergencias[:6],
    }
