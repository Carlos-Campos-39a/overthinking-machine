"""
run.py — CLI principal do projeto TCC Agent Harness.

Uso:
    python run.py                                        # usa config.yaml
    python run.py --model openai/gpt-4o --harness mce    # override de campos
    python run.py --config outro_config.yaml             # config alternativo
    python run.py --list-models                          # lista modelos
    python run.py --list-tasks                           # lista tarefas
    python run.py --list-architectures                   # lista arquiteturas
    python run.py --list-harnesses                       # lista harnesses

Exemplos dos experimentos planejados:
    python run.py --architecture sas --harness zero_shot --task finance_agent --evaluator llm_judge
    python run.py --architecture centralized --harness ace --task finance_agent --evaluator llm_judge
    python run.py --architecture sas --harness meta_harness --task text_classification --evaluator binary
"""
from __future__ import annotations
import sys
from pathlib import Path

# Garante que src/ está no path
sys.path.insert(0, str(Path(__file__).parent))

# Carrega GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY do .env
from dotenv import load_dotenv
load_dotenv()

import typer
import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

from src.llm_factory import LLMFactory
from src.task_base import TaskRegistry
from src.agents.agent_factory import list_architectures
from src.harnesses.manual_harnesses import HARNESSES
from src.runner import run_experiment

app = typer.Typer(
    name="run",
    help="TCC Agent Harness — benchmark de arquiteturas × harnesses × modelos",
    add_completion=False,
)
console = Console()


def _load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Erro: config não encontrado: {config_path}[/red]")
        raise typer.Exit(1)
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg or {}


@app.command()
def main(
    config: str = typer.Option("config.yaml", "--config", "-c", help="Arquivo de configuração YAML"),
    model: str = typer.Option(None, "--model", "-m", help="Override: modelo (provider/name)"),
    architecture: str = typer.Option(None, "--architecture", "-a", help="Override: arquitetura"),
    harness: str = typer.Option(None, "--harness", "-H", help="Override: harness"),
    task: str = typer.Option(None, "--task", "-t", help="Override: tarefa"),
    evaluator: str = typer.Option(None, "--evaluator", "-e", help="Override: evaluator"),
    num_instances: int = typer.Option(None, "--num-instances", "-n", help="Override: nº instâncias"),
    seed: int = typer.Option(None, "--seed", "-s", help="Override: seed"),
    meta_budget: int = typer.Option(None, "--meta-budget", help="Override: iterações do Meta-Harness"),
    n_workers: int = typer.Option(None, "--n-workers", help="Override: n_workers (MAS)"),
    n_agents: int = typer.Option(None, "--n-agents", help="Override: n_agents (Independent/Decentralized)"),
    debate_rounds: int = typer.Option(None, "--debate-rounds", help="Override: debate_rounds"),
    verbose: bool = typer.Option(True, "--verbose/--quiet", help="Verbosidade"),
    list_models: bool = typer.Option(False, "--list-models", help="Lista modelos disponíveis"),
    list_tasks: bool = typer.Option(False, "--list-tasks", help="Lista tarefas disponíveis"),
    list_archs: bool = typer.Option(False, "--list-architectures", help="Lista arquiteturas disponíveis"),
    list_harnesses_flag: bool = typer.Option(False, "--list-harnesses", help="Lista harnesses disponíveis"),
) -> None:
    """Executa um experimento do TCC Agent Harness."""

    # ── Comandos informativos ─────────────────────────────────────────
    if list_models:
        _print_list("Modelos suportados", LLMFactory.list_supported())
        raise typer.Exit()

    if list_tasks:
        _print_list("Tarefas disponíveis", TaskRegistry.list_available())
        raise typer.Exit()

    if list_archs:
        _print_list("Arquiteturas disponíveis", list_architectures())
        raise typer.Exit()

    if list_harnesses_flag:
        _print_list("Harnesses disponíveis", list(HARNESSES.keys()) + ["meta_harness"])
        raise typer.Exit()

    # ── Carrega config base ───────────────────────────────────────────
    cfg = _load_config(config)

    # ── Aplica overrides de linha de comando ──────────────────────────
    if model:           cfg["model"] = model
    if architecture:    cfg["architecture"] = architecture
    if harness:         cfg["harness"] = harness
    if task:            cfg["task"] = task
    if evaluator:       cfg["evaluator"] = evaluator
    if num_instances:   cfg["num_instances"] = num_instances
    if seed is not None: cfg["seed"] = seed
    if meta_budget:     cfg["meta_budget"] = meta_budget

    # Parâmetros MAS via agent_kwargs
    agent_kwargs = cfg.get("agent_kwargs", {})
    if n_workers:       agent_kwargs["n_workers"] = n_workers
    if n_agents:        agent_kwargs["n_agents"] = n_agents
    if debate_rounds:   agent_kwargs["debate_rounds"] = debate_rounds
    if agent_kwargs:    cfg["agent_kwargs"] = agent_kwargs

    # ── Valida campos obrigatórios ────────────────────────────────────
    required = ["model", "architecture", "harness", "task", "evaluator"]
    missing = [f for f in required if not cfg.get(f)]
    if missing:
        console.print(f"[red]Campos obrigatórios ausentes no config: {missing}[/red]")
        raise typer.Exit(1)

    # ── Executa experimento ───────────────────────────────────────────
    try:
        results = run_experiment(cfg, verbose=verbose)
        _print_results(results)
    except KeyboardInterrupt:
        console.print("\n[yellow]Experimento interrompido pelo usuário.[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[red]Erro durante execução: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


def _print_list(title: str, items: list[str]) -> None:
    console.print(f"\n[bold]{title}:[/bold]")
    for item in sorted(items):
        console.print(f"  • {item}")
    console.print()


def _print_results(results: dict) -> None:
    console.print()
    table = Table(title=f"Resultados — {results['run_id']}", show_header=True)
    table.add_column("Instância", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Tempo (s)", justify="right")

    for s in results["scores"]:
        color = "green" if s["score"] >= 0.7 else "yellow" if s["score"] >= 0.4 else "red"
        table.add_row(
            s["instance_id"],
            f"[{color}]{s['score']:.3f}[/{color}]",
            str(s["elapsed_s"]),
        )

    console.print(table)

    mean = results["mean_score"]
    color = "green" if mean >= 0.7 else "yellow" if mean >= 0.4 else "red"
    console.print(
        Panel(
            f"[bold]Score Médio: [{color}]{mean:.4f}[/{color}][/bold]  |  "
            f"Harness: {results['harness_used']}  |  "
            f"Instâncias: {results['num_instances']}",
            title="Resumo",
        )
    )


if __name__ == "__main__":
    app()
