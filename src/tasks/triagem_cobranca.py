"""
triagem_cobranca.py — decidir a ação de cobrança de uma carteira inadimplente.

POR QUE ESTA TAREFA EXISTE
--------------------------
As duas tarefas que a plataforma trazia saturam: com n=10, TODAS as cinco
arquiteturas tiram 1.0 em text_classification. Nesse regime a plataforma não
consegue responder à própria pergunta — é o efeito teto que o Princípio 5
descreve, acontecendo com ela mesma.

Esta tarefa foi desenhada para DISCRIMINAR, e para parecer com uma decisão
operacional de verdade:

  · a política tem PRECEDÊNCIA. Várias regras batem no mesmo caso, e vale a
    primeira. Uma leitura superficial acha a regra mais chamativa, não a que
    manda.
  · os casos têm SINAL CONFLITANTE de propósito. Dívida alta com acordo em dia;
    score bom com atraso enorme; valor baixo que parece irrelevante mas tem
    regra própria.
  · o vocabulário é fechado e as classes, equilibradas — um modelo que responde
    sempre a mesma coisa tira ~0.2, não 0.8.

O que ela mede: capacidade de aplicar uma política escrita a um caso com
informação contraditória. É o que uma operação de crédito e cobrança faz o dia
inteiro, e é onde decomposição e verificação cruzada PODEM ajudar — ou não, e o
ponto do experimento é descobrir qual dos dois.
"""
from __future__ import annotations

import re

from src.task_base import TaskBase, TaskInstance

TASK_TYPE = "classification"
RESPONSE_FORMAT = "single_label"
EVAL_CRITERIA = ["accuracy", "policy_precedence"]

ROTULOS_VALIDOS = [
    "manter_acordo",
    "suspender",
    "digital",
    "operador",
    "juridico",
    "baixa_contabil",
]

# A política vai no enunciado de cada caso: o experimento mede aplicação da
# regra, não memorização dela.
POLITICA = """POLÍTICA DE TRIAGEM — aplique NA ORDEM. Vale a PRIMEIRA regra que casar.

1. Acordo vigente e em dia                          -> manter_acordo
2. Titular falecido ou processo de inventário       -> suspender
3. Saldo devedor <= R$ 200,00                       -> digital
4. Atraso > 720 dias                                -> baixa_contabil
5. Promessa de pagamento quebrada nos últimos 30 dias
   E saldo > R$ 5.000,00                            -> juridico
6. Score de crédito >= 700                          -> digital
7. Nenhuma das anteriores                           -> operador"""


def _reais(valor: float) -> str:
    """Formata em padrão brasileiro. Só o número — aplicar a troca de separador
    ao texto inteiro desfigurava a própria política ('1,' em vez de '1.')."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _caso(**kw) -> str:
    return (
        f"{POLITICA}\n\n"
        f"CASO:\n"
        f"  saldo devedor      : R$ {_reais(kw['saldo'])}\n"
        f"  dias de atraso     : {kw['atraso']}\n"
        f"  score de crédito   : {kw['score']}\n"
        f"  acordo vigente     : {kw['acordo']}\n"
        f"  promessa quebrada  : {kw['promessa']}\n"
        f"  observação         : {kw['obs']}"
    )


# ── Casos ─────────────────────────────────────────────────────────────────────
#
# Cada linha traz por que ela existe. As marcadas ARMADILHA têm um sinal forte
# que aponta para a resposta errada — é onde as arquiteturas se separam, se é
# que se separam.

_INSTANCIAS = [
    # Regra 1 — acordo manda, mesmo com tudo mais gritando outra coisa
    dict(id="tc_01", saldo=18400.00, atraso=430, score=380, acordo="sim, em dia (3ª parcela de 12)",
         promessa="não", obs="renegociado em 01/2026", nota="atraso e saldo altos sugerem juridico; acordo tem precedencia",
         gt="manter_acordo"),
    dict(id="tc_02", saldo=920.50, atraso=95, score=610, acordo="sim, em dia (1ª de 6)",
         promessa="não", obs="acordo firmado no mes passado", nota="caso limpo de regra 1", gt="manter_acordo"),
    dict(id="tc_03", saldo=150.00, atraso=800, score=720, acordo="sim, em dia",
         promessa="sim, há 12 dias", obs="acordo firmado apos negativacao", nota="casaria com 3, 4 e 6; a 1 vem antes",
         gt="manter_acordo"),

    # Regra 2 — suspender vence tudo menos acordo
    dict(id="tc_04", saldo=7300.00, atraso=200, score=450, acordo="não",
         promessa="sim, há 8 dias", obs="titular falecido em 03/2026, espolio em inventario", nota="casaria com a regra 5",
         gt="suspender"),
    dict(id="tc_05", saldo=95.00, atraso=1100, score=800, acordo="não",
         promessa="não", obs="titular falecido, sem espolio localizado", nota="casaria com 3, 4 e 6",
         gt="suspender"),
    dict(id="tc_06", saldo=2400.00, atraso=60, score=500, acordo="não",
         promessa="não", obs="processo de inventario aberto pela familia", nota="caso limpo de regra 2", gt="suspender"),

    # Regra 3 — saldo baixo, antes do atraso
    dict(id="tc_07", saldo=180.00, atraso=900, score=300, acordo="não",
         promessa="não", obs="saldo residual de contrato encerrado", nota="atraso > 720 sugere baixa; saldo baixo vem antes",
         gt="digital"),
    dict(id="tc_08", saldo=45.90, atraso=30, score=520, acordo="não",
         promessa="não", obs="valor residual de fatura", nota="caso limpo de regra 3", gt="digital"),
    dict(id="tc_09", saldo=200.00, atraso=150, score=410, acordo="não",
         promessa="sim, há 5 dias", obs="parcela unica em aberto", nota="exatamente no limite de R$ 200; a regra e <=, entao casa",
         gt="digital"),

    # Regra 4 — atraso longo, antes de promessa e score
    dict(id="tc_10", saldo=12000.00, atraso=1460, score=290, acordo="não",
         promessa="sim, há 20 dias", obs="contrato de 2022, sem contato desde entao", nota="promessa quebrada e saldo alto sugerem juridico; atraso vem antes",
         gt="baixa_contabil"),
    dict(id="tc_11", saldo=3200.00, atraso=730, score=750, acordo="não",
         promessa="não", obs="cliente mudou de endereco em 2024", nota="score alto sugeriria digital; 730 > 720",
         gt="baixa_contabil"),
    dict(id="tc_12", saldo=880.00, atraso=1900, score=350, acordo="não",
         promessa="não", obs="carteira antiga", nota="caso limpo de regra 4", gt="baixa_contabil"),

    # Regra 5 — jurídico exige as DUAS condições
    dict(id="tc_13", saldo=15600.00, atraso=180, score=420, acordo="não",
         promessa="sim, há 11 dias", obs="cliente confirmou pagamento e nao efetivou", nota="as duas condicoes da regra 5", gt="juridico"),
    dict(id="tc_14", saldo=5000.01, atraso=400, score=390, acordo="não",
         promessa="sim, há 29 dias", obs="boleto emitido e nao pago", nota="saldo um centavo acima do limite; promessa no 29o dia",
         gt="juridico"),
    dict(id="tc_15", saldo=48000.00, atraso=300, score=310, acordo="não",
         promessa="sim, há 2 dias", obs="divida de cartao consignado", nota="caso limpo de regra 5", gt="juridico"),

    # Regra 5 NÃO casa — falta uma das condições. Vai para 6 ou 7.
    dict(id="tc_16", saldo=9000.00, atraso=250, score=680, acordo="não",
         promessa="sim, há 45 dias", obs="ultimo contato produtivo em 07/2026", nota="promessa quebrada mas fora da janela de 30 dias",
         gt="operador"),
    dict(id="tc_17", saldo=4800.00, atraso=120, score=650, acordo="não",
         promessa="sim, há 10 dias", obs="cliente pediu novo boleto e nao pagou", nota="promessa recente mas saldo abaixo de R$ 5.000",
         gt="operador"),
    dict(id="tc_18", saldo=6200.00, atraso=90, score=710, acordo="não",
         promessa="sim, há 40 dias", obs="historico de atraso recorrente", nota="promessa fora da janela; cai na regra 6 pelo score",
         gt="digital"),

    # Regra 6 — score alto
    dict(id="tc_19", saldo=2200.00, atraso=45, score=780, acordo="não",
         promessa="não", obs="bom pagador em atraso pontual", nota="caso limpo de regra 6", gt="digital"),
    dict(id="tc_20", saldo=700.00, atraso=700, score=700, acordo="não",
         promessa="não", obs="sem contato registrado", nota="score exatamente 700 (>=) e 700 dias nao passa de 720",
         gt="digital"),

    # Regra 7 — o resto
    dict(id="tc_21", saldo=3400.00, atraso=210, score=540, acordo="não",
         promessa="não", obs="caso padrao da carteira", nota="caso limpo de regra 7", gt="operador"),
    dict(id="tc_22", saldo=1100.00, atraso=365, score=480, acordo="não",
         promessa="não", obs="sem sinal especial", nota="caso limpo de regra 7", gt="operador"),
    dict(id="tc_23", saldo=8700.00, atraso=500, score=699, acordo="não",
         promessa="não", obs="cliente atende mas nao negocia", nota="score um ponto abaixo de 700",
         gt="operador"),
    dict(id="tc_24", saldo=250.00, atraso=100, score=600, acordo="não",
         promessa="não", obs="fatura parcial em aberto", nota="saldo acima de R$ 200 por pouco, score abaixo de 700",
         gt="operador"),
]


class TriagemCobranca(TaskBase):
    """Aplicar uma política de triagem com precedência a casos de cobrança."""

    name = "triagem_cobranca"

    def load(self) -> None:
        self._instances = [
            TaskInstance(
                id=r["id"],
                input=_caso(saldo=r["saldo"], atraso=r["atraso"], score=r["score"],
                            acordo=r["acordo"], promessa=r["promessa"], obs=r["obs"]),
                ground_truth=r["gt"],
                task_type=TASK_TYPE,
                response_format=RESPONSE_FORMAT,
                eval_criteria=EVAL_CRITERIA,
                metadata={
                    "valid_labels": ROTULOS_VALIDOS,
                    "examples": [
                        {"input": "saldo R$ 120,00 / atraso 40 dias / score 500 / sem acordo",
                         "output": "digital"},
                        {"input": "saldo R$ 9.000,00 / atraso 150 dias / score 400 / promessa quebrada há 7 dias",
                         "output": "juridico"},
                    ],
                    # Marca de análise, fora do prompt: serve para eu conferir
                    # se as arquiteturas se separam justamente nos casos
                    # de sinal conflitante.
                    "armadilha": "vem antes" in r["nota"] or "casaria" in r["nota"]
                                 or "mas" in r["nota"] or "limite" in r["nota"],
                    "nota_analise": r["nota"],
                },
            )
            for r in _INSTANCIAS
        ]

    def score(self, output: str, instance: TaskInstance) -> float:
        """
        Acerto exato do rótulo.

        Sem nota parcial de propósito: numa operação, mandar para jurídico um
        caso que era de suspensão por falecimento não é "quase certo" — é um
        erro com consequência. Uma rubrica que desse meio ponto por "chegou
        perto" mediria simpatia, não decisão.
        """
        esperado = instance.ground_truth.strip().lower()
        obtido = (output or "").strip().lower()

        if obtido == esperado:
            return 1.0
        # O modelo às vezes responde com frase; procura o rótulo isolado.
        if re.search(rf"\b{re.escape(esperado)}\b", obtido):
            # Só conta se NENHUM outro rótulo válido aparecer junto — senão a
            # resposta está ambígua e contá-la como acerto seria inflar o score.
            outros = [r for r in ROTULOS_VALIDOS if r != esperado
                      and re.search(rf"\b{re.escape(r)}\b", obtido)]
            return 1.0 if not outros else 0.0
        return 0.0
