"""
evaluators.py — Dois modos de avaliação para o harness benchmark.

BinaryEvaluator  : chama task.score() diretamente, sem custo de API.
                   Ideal para text_classification e tarefas com label exato.

LLMJudgeEvaluator: envia output + rubrica para um LLM juiz externo,
                   extrai score numérico 0.0–1.0.
                   Ideal para finance_agent e tarefas abertas em prosa.
"""
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage

from src.task_base import TaskBase, TaskInstance


@dataclass
class EvalResult:
    score: float        # 0.0 – 1.0
    feedback: str       # texto explicativo usado pelo ACE/MCE


class EvaluatorBase(ABC):
    name: str = ""

    @abstractmethod
    def evaluate(
        self,
        output: str,
        instance: TaskInstance,
        task: TaskBase,
    ) -> EvalResult: ...


# ──────────────────────────────────────────────────────────────────────────────
# 1. Binary Evaluator
# ──────────────────────────────────────────────────────────────────────────────

class BinaryEvaluator(EvaluatorBase):
    """
    Usa task.score() diretamente.
    Sem chamadas de API — avaliação instantânea e determinística.
    """

    name = "binary"

    def evaluate(
        self,
        output: str,
        instance: TaskInstance,
        task: TaskBase,
    ) -> EvalResult:
        score = task.score(output, instance)
        feedback = (
            f"Avaliação binária: score={score:.2f}. "
            f"Ground truth='{instance.ground_truth}'. "
            f"Output='{output[:100]}'"
        )
        return EvalResult(score=score, feedback=feedback)


# ──────────────────────────────────────────────────────────────────────────────
# 2. LLM Judge Evaluator
# ──────────────────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """\
Você é um avaliador especializado rigoroso e imparcial.
Sua função é avaliar a qualidade de respostas de agentes de IA em tarefas analíticas.

Regras:
1. Avalie com base exclusivamente nos critérios fornecidos.
2. Seja calibrado: reserve 0.9+ para respostas excepcionais com cobertura completa.
3. 0.7–0.89 = boa, cobertura substancial com pequenas lacunas.
4. 0.4–0.69 = parcial, cobre apenas aspectos superficiais.
5. <0.4 = fraca, incorreta ou fora do escopo.
6. Sua resposta final DEVE conter exatamente uma linha com o formato:
   SCORE: <número entre 0.0 e 1.0>
   Seguida de uma linha FEEDBACK: <explicação concisa em 1-2 frases>.
"""

_JUDGE_TEMPLATE = """\
TAREFA:
{task_input}

CRITÉRIOS DE AVALIAÇÃO:
{criteria}

RESPOSTA DO AGENTE:
{agent_output}

CONTEXTO ESPERADO (palavras-chave / tópicos que uma boa resposta deve cobrir):
{ground_truth}

Avalie a resposta do agente. Responda com:
SCORE: <0.0 a 1.0>
FEEDBACK: <explicação concisa>
"""


def _extract_score(text: str) -> float | None:
    """Extrai o número após 'SCORE:' da resposta do juiz."""
    match = re.search(r"SCORE\s*:\s*([0-9]*\.?[0-9]+)", text, re.IGNORECASE)
    if match:
        val = float(match.group(1))
        return max(0.0, min(1.0, val))
    # Fallback: primeiro número float no texto
    numbers = re.findall(r"\b(0?\.\d+|[01]\.0+|[01])\b", text)
    if numbers:
        return max(0.0, min(1.0, float(numbers[0])))
    return None


def _extract_feedback(text: str) -> str:
    """Extrai o texto após 'FEEDBACK:' da resposta do juiz."""
    match = re.search(r"FEEDBACK\s*:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()[:500]
    return text.strip()[:500]


class LLMJudgeEvaluator(EvaluatorBase):
    """
    Avaliador baseado em LLM juiz.

    Envia ao juiz:
      - O input original da tarefa
      - Os eval_criteria da instância
      - O output do agente
      - O ground_truth como contexto esperado

    Extrai score e feedback da resposta do juiz.
    Fallback para 0.5 se a extração falhar.
    """

    name = "llm_judge"

    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    def evaluate(
        self,
        output: str,
        instance: TaskInstance,
        task: TaskBase,
    ) -> EvalResult:
        criteria_text = "\n".join(f"- {c}" for c in instance.eval_criteria)
        prompt = _JUDGE_TEMPLATE.format(
            task_input=instance.input,
            criteria=criteria_text,
            agent_output=output,
            ground_truth=str(instance.ground_truth),
        )

        response = self.llm.invoke([
            SystemMessage(content=_JUDGE_SYSTEM),
            HumanMessage(content=prompt),
        ])
        raw = response.content.strip()

        score = _extract_score(raw)
        if score is None:
            score = 0.5  # fallback conservador

        feedback = _extract_feedback(raw)
        return EvalResult(score=score, feedback=feedback)


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

EVALUATORS: dict[str, type[EvaluatorBase]] = {
    "binary":    BinaryEvaluator,
    "llm_judge": LLMJudgeEvaluator,
}


def get_evaluator(name: str, **kwargs) -> EvaluatorBase:
    """
    Retorna instância do evaluator pelo nome.

    llm_judge requer llm=<BaseChatModel>:
        get_evaluator("llm_judge", llm=my_llm)

    binary não requer parâmetros:
        get_evaluator("binary")
    """
    if name not in EVALUATORS:
        raise KeyError(
            f"Evaluator '{name}' não encontrado. Disponíveis: {list(EVALUATORS)}"
        )
    return EVALUATORS[name](**kwargs)
