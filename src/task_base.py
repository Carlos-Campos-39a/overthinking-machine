from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import importlib
import pkgutil
from typing import Any


@dataclass
class TaskInstance:
    id: str
    input: str
    ground_truth: Any
    task_type: str
    response_format: str
    eval_criteria: list[str]
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskResult:
    instance_id: str
    agent_output: str
    score: float
    trace: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class TaskBase(ABC):

    name: str = ""

    def __init__(self, num_instances: int = 10, seed: int = 42):
        self.num_instances = num_instances
        self.seed = seed
        self._instances: list[TaskInstance] = []

    @abstractmethod
    def load(self) -> None: ...

    def sample(self, n: int | None = None) -> list[TaskInstance]:
        if not self._instances:
            self.load()
        import random
        rng = random.Random(self.seed)
        pool = self._instances[:]
        rng.shuffle(pool)
        return pool[:n if n is not None else self.num_instances]

    @abstractmethod
    def score(self, output: str, instance: TaskInstance) -> float: ...

    def prompt_for_judge(self, output: str, instance: TaskInstance) -> str:
        criteria_text = "\n".join(f"- {c}" for c in instance.eval_criteria)
        return (
            f"Você é um avaliador imparcial.\n\n"
            f"TAREFA:\n{instance.input}\n\n"
            f"RESPOSTA DO AGENTE:\n{output}\n\n"
            f"CRITÉRIOS DE AVALIAÇÃO:\n{criteria_text}\n\n"
            f"Avalie de 0.0 a 1.0 com base nos critérios acima.\n"
            f"Responda APENAS com um número entre 0.0 e 1.0."
        )


class TaskRegistry:

    _registry: dict[str, type[TaskBase]] = {}
    _loaded: bool = False

    @classmethod
    def _discover(cls) -> None:
        if cls._loaded:
            return
        tasks_path = Path(__file__).parent / "tasks"
        for _, module_name, _ in pkgutil.iter_modules([str(tasks_path)]):
            full_name = f"src.tasks.{module_name}"
            try:
                mod = importlib.import_module(full_name)
                for attr_name in dir(mod):
                    obj = getattr(mod, attr_name)
                    if (
                        isinstance(obj, type)
                        and issubclass(obj, TaskBase)
                        and obj is not TaskBase
                        and obj.name
                    ):
                        cls._registry[obj.name] = obj
            except Exception as e:
                print(f"[TaskRegistry] Aviso: falha ao importar '{full_name}': {e}")
        cls._loaded = True

    @classmethod
    def get(cls, name: str, **kwargs: Any) -> TaskBase:
        cls._discover()
        if name not in cls._registry:
            raise KeyError(
                f"Task '{name}' não encontrada. "
                f"Disponíveis: {list(cls._registry.keys())}"
            )
        return cls._registry[name](**kwargs)

    @classmethod
    def list_available(cls) -> list[str]:
        cls._discover()
        return sorted(cls._registry.keys())