"""
meta_harness.py — Loop de busca automática de harnesses (Paper 2).

Baseado em: Lee et al. (2026) "Meta-Harness: End-to-End Optimization of Model Harnesses" (arXiv:2603.28052)

Algoritmo (Algorithm 1 do paper):
    Input: tasks X, LLM M, proposer P, iterations N
    Initialize: population H (= {zero_shot})
    Initialize: filesystem D = ∅
    for H in H do:
        E_H ← Evaluate(H, M, X)
        D ← D ∪ {(H, E_H)}
    for t = 1..N do:
        P queries filesystem D
        P proposes k new harnesses {H_1, ..., H_k}
        for H in {H_1, ..., H_k} do:
            if H passes interface validation:
                D ← D ∪ {(H, Evaluate(H, M, X))}
    return Pareto frontier stored in D

Diferenças de implementação para o TCC:
    - P recebe o filesystem como string no prompt (em vez de acesso real)
      pois o proposer é um LLM, não um coding agent com shell
    - k=1 por iteração (paper usa k=2-3, mas k=1 é mais estável)
    - Interface validation: verifica se o código gerado é válido Python
      com a assinatura correta `build_messages(instance) -> HarnessOutput`
    - Pareto frontier simplificada: retorna o harness com maior score médio
"""
from __future__ import annotations
import json
import textwrap
import traceback
from pathlib import Path
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage

from src.task_base import TaskBase, TaskInstance
from src.harnesses.harness_base import HarnessBase, HarnessOutput
from src.llm_text import texto_da_resposta
from src.harnesses.manual_harnesses import (
    ZeroShotHarness,
    _system,
    _fmt,
    SYSTEM_PROMPTS,
    FORMAT_INSTRUCTIONS,
)
from src.evaluators.evaluators import EvaluatorBase


# ──────────────────────────────────────────────────────────────────────────────
# DynamicHarness — executa código gerado pelo proposer via exec()
# ──────────────────────────────────────────────────────────────────────────────

_HARNESS_INTERFACE_CHECK = """
def _check(build_messages):
    from src.task_base import TaskInstance
    from src.harnesses.harness_base import HarnessOutput
    import inspect
    sig = inspect.signature(build_messages)
    assert 'instance' in sig.parameters, "Função deve aceitar parâmetro 'instance'"
    return True
"""

_HARNESS_SKELETON = """\
# Auto-generated harness by Meta-Harness proposer
from __future__ import annotations
from langchain_core.messages import HumanMessage, SystemMessage
from src.task_base import TaskInstance
from src.harnesses.harness_base import HarnessBase, HarnessOutput

# Utilitários disponíveis (importados do manual_harnesses)
# _system(instance)  → system prompt por task_type
# _fmt(instance)     → instrução de formato
# _read_kb(task_name) → lê knowledge base (ACE)
# _read_pokedex(task_name) → lê pokédex (MCE)

{code}
"""


class DynamicHarness(HarnessBase):
    """
    Harness que executa código Python gerado dinamicamente pelo proposer.
    Fallback para ZeroShotHarness se o código for inválido.
    """

    name = "dynamic"

    def __init__(self, code: str, task_name: str = ""):
        self.code = code
        self.task_name = task_name
        self._build_fn: Callable | None = None
        self._valid: bool = False
        self._compile_error: str = ""
        self._try_compile()

    def _try_compile(self) -> None:
        """Tenta compilar o código e extrair a função build_messages."""
        namespace: dict[str, Any] = {
            "_system": _system,
            "_fmt": _fmt,
            "SYSTEM_PROMPTS": SYSTEM_PROMPTS,
            "FORMAT_INSTRUCTIONS": FORMAT_INSTRUCTIONS,
        }
        try:
            exec(self.code, namespace)  # noqa: S102
            if "build_messages" not in namespace:
                self._compile_error = "Código não define função 'build_messages'"
                return
            fn = namespace["build_messages"]
            import inspect
            sig = inspect.signature(fn)
            if "instance" not in sig.parameters:
                self._compile_error = "build_messages deve aceitar parâmetro 'instance'"
                return
            self._build_fn = fn
            self._valid = True
        except Exception as e:
            self._compile_error = str(e)

    def build_messages(self, instance: TaskInstance) -> HarnessOutput:
        """Executa o harness dinâmico. Fallback para zero_shot se inválido."""
        if not self._valid or self._build_fn is None:
            return ZeroShotHarness().build_messages(instance)
        try:
            result = self._build_fn(instance)
            if isinstance(result, HarnessOutput):
                return result
            # Se retornou list de mensagens, envolve em HarnessOutput
            return HarnessOutput(messages=result, metadata={"harness": "dynamic"})
        except Exception:
            return ZeroShotHarness().build_messages(instance)


# ──────────────────────────────────────────────────────────────────────────────
# MetaHarness — loop de busca
# ──────────────────────────────────────────────────────────────────────────────

_PROPOSER_SYSTEM = """\
Você é um engenheiro de harnesses especializado em otimizar o contexto que um LLM recebe.

Um "harness" é uma função Python com a assinatura:
    def build_messages(instance: TaskInstance) -> HarnessOutput

Onde TaskInstance tem os campos:
    - instance.id          (str)  identificador
    - instance.input       (str)  a pergunta/tarefa para o modelo
    - instance.task_type   (str)  ex: "market_search", "classification"
    - instance.response_format (str) ex: "long_prose", "single_label"
    - instance.eval_criteria  (list[str]) critérios de avaliação
    - instance.metadata    (dict) dados extras, ex: metadata['examples'] para few-shot
    - instance.ground_truth (any) resposta esperada

E HarnessOutput é construído como:
    HarnessOutput(messages=[SystemMessage(...), HumanMessage(...)], metadata={...})

Utilitários disponíveis no namespace do harness (já importados):
    _system(instance)  → retorna o system prompt adequado ao task_type
    _fmt(instance)     → retorna instrução de formato adequada ao response_format
    SystemMessage, HumanMessage  → do langchain_core.messages
    HarnessOutput, TaskInstance  → dos módulos do projeto

Você tem acesso completo ao histórico de todos os candidatos anteriores.
Analise os scores e traces para identificar o que funcionou e o que falhou.
Proponha um harness novo que melhore sobre os candidatos anteriores.

IMPORTANTE: Responda APENAS com o código Python da função build_messages.
Sem explicações, sem markdown, sem imports (eles já existem no namespace).
Comece diretamente com: def build_messages(instance: TaskInstance) -> HarnessOutput:
"""

_PROPOSER_TEMPLATE = """\
## Missão
Proponha um harness melhorado para a tarefa: {task_name}
Avaliador usado: {evaluator_name}
Score do melhor candidato atual: {best_score:.4f}

## Histórico de candidatos
{candidates_summary}

## Exemplos de traces do candidato com MAIOR score (para entender o que funciona)
{best_traces}

## Exemplos de traces do candidato com MENOR score (para entender o que falha)
{worst_traces}

## Código do melhor candidato atual
```python
{best_code}
```

## Instrução
Analise os traces. Identifique padrões de falha. Proponha um harness melhorado.
Foque em: (1) qualidade do prompt, (2) contexto injetado, (3) formato de resposta.
Responda APENAS com o código Python da função build_messages:
"""


class MetaHarness:
    """
    Implementação do loop de busca do Meta-Harness (Lee et al., 2026).

    Usa um proposer LLM para iterar sobre candidatos de harness,
    avaliando cada um e salvando código + scores + traces no filesystem.
    """

    def __init__(
        self,
        proposer_llm: BaseChatModel,
        task: TaskBase,
        evaluator: EvaluatorBase,
        agent_factory: Callable,
        candidates_dir: Path,
        meta_budget: int = 5,
        verbose: bool = True,
    ):
        self.proposer_llm = proposer_llm
        self.task = task
        self.evaluator = evaluator
        self.agent_factory = agent_factory
        self.candidates_dir = candidates_dir
        self.meta_budget = meta_budget
        self.verbose = verbose

        self._population: list[dict] = []  # {harness, code, score, scores_by_id, traces}

    def search(self, instances: list[TaskInstance]) -> HarnessBase:
        """
        Executa o loop de busca e retorna o melhor harness encontrado.
        """
        if self.verbose:
            print(f"\n  [Meta-Harness] Iniciando busca — {self.meta_budget} iterações")

        # ── Seed: zero_shot como candidato inicial ────────────────────
        seed_code = textwrap.dedent("""\
            def build_messages(instance: TaskInstance) -> HarnessOutput:
                content = f"{instance.input}\\n\\n{_fmt(instance)}".strip()
                return HarnessOutput(
                    messages=[
                        SystemMessage(content=_system(instance)),
                        HumanMessage(content=content),
                    ],
                    metadata={"harness": "zero_shot_seed"},
                )
        """)
        seed_harness = DynamicHarness(code=seed_code, task_name=self.task.name)
        seed_result = self._evaluate_candidate(
            harness=seed_harness,
            code=seed_code,
            instances=instances,
            candidate_idx=0,
        )
        self._population.append(seed_result)

        if self.verbose:
            print(f"  [Meta-Harness] Candidato 0 (seed/zero_shot): score={seed_result['mean_score']:.4f}")

        # ── Loop de busca ─────────────────────────────────────────────
        for iteration in range(1, self.meta_budget + 1):
            # Proposer lê o filesystem (representado como summary)
            new_code = self._propose_harness()

            if not new_code:
                if self.verbose:
                    print(f"  [Meta-Harness] Iteração {iteration}: proposer não gerou código válido")
                continue

            candidate = DynamicHarness(code=new_code, task_name=self.task.name)

            if not candidate._valid:
                if self.verbose:
                    print(f"  [Meta-Harness] Iteração {iteration}: código inválido — {candidate._compile_error}")
                # Ainda salva o código para o proposer aprender do erro
                self._save_candidate(
                    candidate_idx=len(self._population),
                    code=new_code,
                    scores={},
                    traces=[],
                    mean_score=0.0,
                    error=candidate._compile_error,
                )
                continue

            result = self._evaluate_candidate(
                harness=candidate,
                code=new_code,
                instances=instances,
                candidate_idx=len(self._population),
            )
            self._population.append(result)

            if self.verbose:
                best = max(self._population, key=lambda x: x["mean_score"])
                print(
                    f"  [Meta-Harness] Iteração {iteration}: "
                    f"score={result['mean_score']:.4f} | "
                    f"melhor={best['mean_score']:.4f}"
                )

        # ── Retorna melhor harness ────────────────────────────────────
        best = max(self._population, key=lambda x: x["mean_score"])
        if self.verbose:
            print(
                f"\n  [Meta-Harness] Busca concluída. "
                f"Melhor score: {best['mean_score']:.4f} "
                f"(candidato {best['idx']})\n"
            )
        return best["harness"]

    def _evaluate_candidate(
        self,
        harness: HarnessBase,
        code: str,
        instances: list[TaskInstance],
        candidate_idx: int,
    ) -> dict:
        """Avalia um harness em todas as instâncias e salva no filesystem."""
        agent = self.agent_factory()
        scores_by_id: dict[str, float] = {}
        traces: list[dict] = []

        for instance in instances:
            try:
                harness_output = harness.build_messages(instance)
                output = agent.run(harness_output.messages)
                eval_result = self.evaluator.evaluate(output, instance, self.task)

                scores_by_id[instance.id] = eval_result.score
                traces.append({
                    "instance_id": instance.id,
                    "input": instance.input[:200],
                    "output": output[:400],
                    "score": eval_result.score,
                    "feedback": eval_result.feedback,
                })
            except Exception as e:
                scores_by_id[instance.id] = 0.0
                traces.append({
                    "instance_id": instance.id,
                    "error": str(e),
                    "score": 0.0,
                })

        mean_score = (
            sum(scores_by_id.values()) / len(scores_by_id)
            if scores_by_id else 0.0
        )

        self._save_candidate(candidate_idx, code, scores_by_id, traces, mean_score)

        return {
            "idx": candidate_idx,
            "harness": harness,
            "code": code,
            "mean_score": mean_score,
            "scores_by_id": scores_by_id,
            "traces": traces,
        }

    def _save_candidate(
        self,
        candidate_idx: int,
        code: str,
        scores: dict,
        traces: list,
        mean_score: float,
        error: str = "",
    ) -> None:
        """Persiste candidato no filesystem (como no paper)."""
        candidate_dir = self.candidates_dir / f"candidate_{candidate_idx:03d}"
        candidate_dir.mkdir(parents=True, exist_ok=True)

        (candidate_dir / "harness.py").write_text(code, encoding="utf-8")
        (candidate_dir / "scores.json").write_text(
            json.dumps({"mean_score": mean_score, "by_instance": scores, "error": error},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (candidate_dir / "trace.jsonl").open("w", encoding="utf-8") as f:
            for t in traces:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")

    def _propose_harness(self) -> str | None:
        """
        Proposer lê o filesystem de candidatos e propõe novo harness.
        Retorna código Python como string, ou None se falhar.
        """
        if not self._population:
            return None

        best = max(self._population, key=lambda x: x["mean_score"])
        worst = min(self._population, key=lambda x: x["mean_score"])

        # Summary de todos os candidatos
        candidates_summary = "\n".join(
            f"  Candidato {c['idx']}: score={c['mean_score']:.4f}"
            for c in sorted(self._population, key=lambda x: x["mean_score"], reverse=True)
        )

        # Traces do melhor
        best_traces_text = "\n".join(
            f"  [{t['instance_id']}] score={t.get('score', 0):.2f} "
            f"| output: {t.get('output', '')[:150]}"
            for t in best["traces"][:3]
        )

        # Traces do pior
        worst_traces_text = "\n".join(
            f"  [{t['instance_id']}] score={t.get('score', 0):.2f} "
            f"| feedback: {t.get('feedback', t.get('error', ''))[:150]}"
            for t in worst["traces"][:3]
        )

        prompt = _PROPOSER_TEMPLATE.format(
            task_name=self.task.name,
            evaluator_name=self.evaluator.name,
            best_score=best["mean_score"],
            candidates_summary=candidates_summary,
            best_traces=best_traces_text or "(sem traces)",
            worst_traces=worst_traces_text or "(sem traces)",
            best_code=best["code"],
        )

        try:
            response = self.proposer_llm.invoke([
                SystemMessage(content=_PROPOSER_SYSTEM),
                HumanMessage(content=prompt),
            ])
            raw = texto_da_resposta(response)

            # Remove markdown code fences se presentes
            if raw.startswith("```"):
                lines = raw.splitlines()
                # Remove primeira linha (```python) e última (```)
                raw = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )

            # Valida que é Python sintático
            compile(raw, "<meta_harness_proposer>", "exec")
            return raw

        except SyntaxError as e:
            if self.verbose:
                print(f"  [Meta-Harness] SyntaxError na proposta: {e}")
            return None
        except Exception as e:
            if self.verbose:
                print(f"  [Meta-Harness] Erro no proposer: {e}")
            return None
