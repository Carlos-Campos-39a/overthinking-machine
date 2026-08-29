"""
minha_tarefa.py — TEMPLATE de tarefa customizada da Overthinking Machine.

COMO USAR
---------
1. Copie este arquivo para  src/tasks/  com um nome próprio (ex: triagem_ticket.py)
2. Troque o valor de `name` — é por ele que a tarefa é referenciada em todo lugar
3. Preencha _INSTANCIAS com os seus dados reais
4. Ajuste score() ao seu critério de acerto
5. Confirme que foi registrada:   python run.py --list-tasks

A descoberta é automática: qualquer subclasse de TaskBase dentro de src/tasks/
com um `name` preenchido entra no registro sozinha.

DEPOIS DE CRIAR, siga o protocolo (boilerplate/README.md):
    validar com n=1  →  escolher modelo  →  ablação de prompt  →  matriz final
Não pule direto para a matriz.
"""
from __future__ import annotations
import re
from src.task_base import TaskBase, TaskInstance


# ── Configuração da tarefa ────────────────────────────────────────────────────
#
# task_type       controla o system prompt padrão do harness. Use um dos que já
#                 existem em src/harnesses/manual_harnesses.py (classification,
#                 market_search, legal_analysis) ou adicione o seu lá.
# response_format "single_label" (resposta curta) ou "long_prose" (texto longo).
#                 Determina a instrução de formato injetada no prompt.
# eval_criteria   usado pelo avaliador llm_judge para montar a rubrica.

TASK_TYPE       = "classification"
RESPONSE_FORMAT = "single_label"
EVAL_CRITERIA   = ["accuracy", "label_match"]

# Vocabulário fechado de respostas válidas.
# IMPORTANTE: se a sua tarefa tem um conjunto fixo de rótulos, declare aqui.
# O harness injeta essa lista no prompt automaticamente — sem isso o modelo
# responde algo semanticamente correto mas fora do vocabulário ("Futebol"
# quando o esperado era "Esporte") e o avaliador binário conta como erro.
ROTULOS_VALIDOS = ["aprovado", "reprovado", "pendente"]


# ── Seus dados ────────────────────────────────────────────────────────────────
#
# Regra prática de tamanho: pelo menos 20 instâncias. Com menos, um único erro
# vira um salto grande demais no score para distinguir sinal de ruído.
# Equilibre as classes — 18 "aprovado" e 2 "reprovado" faz um classificador que
# só responde "aprovado" parecer excelente.

_INSTANCIAS = [
    {
        "id": "t01",
        "input": "Cliente com 3 anos de histórico, sem atrasos, solicita aumento de limite de 20%.",
        "ground_truth": "aprovado",
    },
    {
        "id": "t02",
        "input": "Cliente cadastrado há 2 meses, dois pagamentos em atraso, solicita crédito.",
        "ground_truth": "reprovado",
    },
    {
        "id": "t03",
        "input": "Cliente antigo e adimplente, mas documentação de renda vencida há 40 dias.",
        "ground_truth": "pendente",
    },
    # ... adicione as suas. Mínimo recomendado: 20.
]


class MinhaTarefa(TaskBase):
    """Descreva aqui, em uma linha, o que esta tarefa mede."""

    name = "minha_tarefa"   # ← TROQUE. É o identificador usado em --task

    def load(self) -> None:
        self._instances = [
            TaskInstance(
                id=r["id"],
                input=r["input"],
                ground_truth=r["ground_truth"],
                task_type=TASK_TYPE,
                response_format=RESPONSE_FORMAT,
                eval_criteria=EVAL_CRITERIA,
                metadata={
                    "valid_labels": ROTULOS_VALIDOS,
                    # exemplos usados pelo harness few_shot
                    "examples": [
                        {"input": _INSTANCIAS[0]["input"], "output": _INSTANCIAS[0]["ground_truth"]},
                    ],
                },
            )
            for r in _INSTANCIAS
        ]

    def score(self, output: str, instance: TaskInstance) -> float:
        """
        Nota de 0.0 a 1.0 para a resposta do agente.

        Esta implementação: match exato, com fallback que procura qualquer
        rótulo válido no texto (o modelo às vezes responde "Resposta: aprovado").
        Adapte ao seu critério — F1, distância de edição, regex sobre um campo
        estruturado, o que fizer sentido para a sua tarefa.

        Se a sua avaliação for subjetiva (texto longo, sem gabarito único),
        deixe este método simples e use o avaliador llm_judge no experimento.
        """
        limpo = output.strip().lower()
        esperado = str(instance.ground_truth).strip().lower()

        if limpo == esperado:
            return 1.0
        for rotulo in ROTULOS_VALIDOS:
            if re.search(rf"\b{re.escape(rotulo.lower())}\b", limpo):
                return 1.0 if rotulo.lower() == esperado else 0.0
        return 0.0   # nenhum rótulo reconhecido
