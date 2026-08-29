"""
runner.py — Orquestrador central do experimento.

Fluxo:
    config.yaml
      → LLMFactory.create(model)
      → AgentFactory.create(architecture)
      → TaskRegistry.get(task)
      → get_harness(harness)
      → para cada instância: harness → agent.run() → evaluator
      → salva runs/{run_id}/config.json + scores.json + trace.jsonl

Para ACE e MCE:
    → chama harness.record_result() após cada avaliação
    → chama harness.flush() ao fim da execução
    → persiste knowledge_base/ e pokedex/ entre execuções

Para meta_harness:
    → delega para MetaHarness.search() que retorna o melhor harness
    → usa o harness encontrado para a avaliação final
"""
from __future__ import annotations
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.llm_factory import LLMFactory
from src.task_base import TaskRegistry, TaskInstance
from src.harnesses.manual_harnesses import get_harness, AceHarness, MceHarness
from src.agents.agent_factory import create_agent
from src.evaluators.evaluators import get_evaluator, EvalResult


RUNS_DIR = Path("runs")


def _run_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    return f"run_{ts}_{uid}"


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _sum_tokens(agent_trace: list[dict]) -> dict:
    """Soma os tokens (input/output/total) de todas as chamadas de LLM registradas no trace."""
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0}
    for step in agent_trace:
        usage = step.get("usage")
        if usage:
            totals["input_tokens"] += usage.get("input_tokens", 0)
            totals["output_tokens"] += usage.get("output_tokens", 0)
            totals["total_tokens"] += usage.get("total_tokens", 0)
            totals["llm_calls"] += 1
    return totals


def run_experiment(config: dict, verbose: bool = True) -> dict:
    """
    Executa um experimento completo a partir de um dict de configuração.

    Args:
        config: dicionário com campos:
            model          (str)  ex: "google/gemini-2.0-flash"
            architecture   (str)  ex: "sas"
            harness        (str)  ex: "ace"
            task           (str)  ex: "finance_agent"
            evaluator      (str)  ex: "llm_judge"
            num_instances  (int)  ex: 5
            seed           (int)  ex: 42
            agent_kwargs   (dict) parâmetros extras para create_agent
            meta_budget    (int)  iterações do Meta-Harness (se harness=meta_harness)

        verbose: se True, imprime progresso no terminal

    Returns:
        Dicionário com resultados do experimento:
            run_id, config, scores, mean_score, num_instances, harness_used
    """
    run_id = _run_id()
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Run: {run_id}")
        print(f"  Modelo:       {config['model']}")
        print(f"  Arquitetura:  {config['architecture']}")
        print(f"  Harness:      {config['harness']}")
        print(f"  Tarefa:       {config['task']}")
        print(f"  Avaliador:    {config['evaluator']}")
        print(f"  Instâncias:   {config.get('num_instances', 5)}")
        print(f"{'='*60}\n")

    # ── Instancia LLM ─────────────────────────────────────────────────
    llm = LLMFactory.create(config["model"])

    # ── Instancia tarefa ──────────────────────────────────────────────
    task = TaskRegistry.get(
        config["task"],
        num_instances=config.get("num_instances", 5),
        seed=config.get("seed", 42),
    )

    # Se instance_ids foi fornecido, carrega todas as instâncias e filtra pelos IDs
    instance_ids: list[str] = config.get("instance_ids", [])
    if instance_ids:
        task.load()
        id_set = set(instance_ids)
        instances = [inst for inst in task._instances if inst.id in id_set]
        if not instances:
            # Fallback: se nenhum ID bater, usa sample() normalmente
            instances = task.sample()
    else:
        instances = task.sample()

    # ── System prompt customizado (ablação de prompt) ─────────────────
    # Quando presente, substitui o system prompt padrão da tarefa em todas as
    # instâncias. Usado pelo experimento de sensibilidade de prompt, que roda a
    # mesma tarefa com cláusulas removidas para medir a contribuição de cada uma.
    system_override = config.get("system_prompt_override")
    if system_override is not None:
        for inst in instances:
            inst.metadata = {**inst.metadata, "system_override": system_override}

    # ── Instancia agente ──────────────────────────────────────────────
    agent_kwargs = config.get("agent_kwargs", {})
    agent = create_agent(config["architecture"], llm=llm, **agent_kwargs)

    # ── Instancia evaluator ───────────────────────────────────────────
    eval_name = config.get("evaluator", "binary")
    if eval_name == "llm_judge":
        judge_model = config.get("judge_model", config["model"])
        judge_llm = LLMFactory.create(judge_model)
        evaluator = get_evaluator("llm_judge", llm=judge_llm)
    else:
        evaluator = get_evaluator("binary")

    # ── Instancia harness ─────────────────────────────────────────────
    harness_name = config.get("harness", "zero_shot")
    task_name = config["task"]

    if harness_name == "meta_harness":
        # Meta-Harness: busca automática de harnesses
        harness = _setup_meta_harness(
            config=config,
            llm=llm,
            task=task,
            instances=instances,
            evaluator=evaluator,
            run_dir=run_dir,
            verbose=verbose,
        )
        harness_used = f"meta_harness->{getattr(harness, 'name', 'dynamic')}"

    elif harness_name in ("ace", "mce"):
        harness = get_harness(harness_name, llm=llm, task_name=task_name)
        harness_used = harness_name

    else:
        harness = get_harness(harness_name)
        harness_used = harness_name

    # ── Loop principal ────────────────────────────────────────────────
    scores: list[dict] = []
    trace_path = run_dir / "trace.jsonl"

    for idx, instance in enumerate(instances):
        if verbose:
            print(f"  [{idx+1}/{len(instances)}] {instance.id}", end="", flush=True)

        t0 = time.time()

        # Harness constrói as mensagens
        harness_output = harness.build_messages(instance)

        # Agente executa
        output = agent.run(harness_output.messages)

        # Avaliação
        result: EvalResult = evaluator.evaluate(output, instance, task)

        elapsed = time.time() - t0
        agent_trace = agent.trace_dicts()
        tokens = _sum_tokens(agent_trace)

        if verbose:
            print(f" -> score={result.score:.3f} ({elapsed:.1f}s, {tokens['total_tokens']} tokens, {tokens['llm_calls']} chamadas)")

        # Registro no trace
        trace_record = {
            "instance_id": instance.id,
            "input": instance.input,
            "output": output,
            "score": result.score,
            "feedback": result.feedback,
            "elapsed_s": round(elapsed, 2),
            "tokens": tokens,
            "harness": harness_used,
            "harness_metadata": harness_output.metadata,
            "agent_trace": agent_trace,
        }
        _append_jsonl(trace_path, trace_record)

        scores.append({
            "instance_id": instance.id,
            "score": result.score,
            "elapsed_s": round(elapsed, 2),
            "tokens": tokens,
        })

        # Atualiza memória (ACE / MCE)
        if isinstance(harness, (AceHarness, MceHarness)):
            harness.record_result(
                instance=instance,
                output=output,
                score=result.score,
                feedback=result.feedback,
            )

    # Flush final para ACE / MCE
    if isinstance(harness, (AceHarness, MceHarness)):
        harness.flush()

    # ── Salva resultados ──────────────────────────────────────────────
    n = len(scores)
    mean_score = sum(s["score"] for s in scores) / n if n else 0.0
    mean_elapsed_s = sum(s["elapsed_s"] for s in scores) / n if n else 0.0
    mean_input_tokens = sum(s["tokens"]["input_tokens"] for s in scores) / n if n else 0.0
    mean_output_tokens = sum(s["tokens"]["output_tokens"] for s in scores) / n if n else 0.0
    mean_total_tokens = sum(s["tokens"]["total_tokens"] for s in scores) / n if n else 0.0
    mean_llm_calls = sum(s["tokens"]["llm_calls"] for s in scores) / n if n else 0.0

    results = {
        "run_id": run_id,
        "config": config,
        "harness_used": harness_used,
        "num_instances": len(instances),
        "mean_score": round(mean_score, 4),
        "mean_elapsed_s": round(mean_elapsed_s, 3),
        "mean_input_tokens": round(mean_input_tokens, 1),
        "mean_output_tokens": round(mean_output_tokens, 1),
        "mean_total_tokens": round(mean_total_tokens, 1),
        "mean_llm_calls": round(mean_llm_calls, 2),
        "scores": scores,
    }

    _save_json(run_dir / "config.json", config)
    _save_json(run_dir / "scores.json", results)

    if verbose:
        print(f"\n  [OK] Score médio: {mean_score:.4f}")
        print(f"  [OK] Resultados salvos em: {run_dir}/\n")

    return results


def _setup_meta_harness(
    config: dict,
    llm,
    task,
    instances,
    evaluator,
    run_dir: Path,
    verbose: bool,
):
    """
    Inicializa e roda o loop de busca do Meta-Harness.
    Retorna o melhor harness encontrado.
    """
    from src.meta_harness.meta_harness import MetaHarness

    meta_budget = config.get("meta_budget", 5)
    candidates_dir = RUNS_DIR / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    meta = MetaHarness(
        proposer_llm=llm,
        task=task,
        evaluator=evaluator,
        agent_factory=lambda: create_agent(
            config["architecture"],
            llm=llm,
            **config.get("agent_kwargs", {}),
        ),
        candidates_dir=candidates_dir,
        meta_budget=meta_budget,
        verbose=verbose,
    )

    best_harness = meta.search(instances=instances)
    return best_harness
