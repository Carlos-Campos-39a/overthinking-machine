"""
tarefa_declarativa.py — o interpretador de EspecTarefa.

Transforma uma spec (dado) numa TaskBase que o runner já sabe rodar. Não executa
nada de terceiro: monta texto e compara rótulo.

A classe NÃO é registrada no TaskRegistry de propósito — `name` fica vazio no
nível da classe, que é o que o descobridor usa para decidir o que registrar. Uma
tarefa declarativa só existe com uma spec junto; aparecer em `--list-tasks` como
se fosse rodável sozinha seria mentira.
"""
from __future__ import annotations

import re

from src.task_base import TaskBase, TaskInstance
from src.tasks.tarefa_spec import EspecTarefa, validar_tarefa


class TarefaDeclarativa(TaskBase):
    """Tarefa definida por especificação, trazida por quem vai rodar."""

    # Vazio = invisível para o TaskRegistry. Ver docstring do módulo.
    name = ""

    def __init__(self, spec: EspecTarefa | dict, num_instances: int = 10, seed: int = 42):
        super().__init__(num_instances=num_instances, seed=seed)
        self.spec = validar_tarefa(spec)
        # Instância tem nome; a classe, não.
        self.name = self.spec.nome

    def load(self) -> None:
        # Exemplos no formato que os harnesses embutidos leem
        # (manual_harnesses.FewShotHarness espera 'input'/'output').
        exemplos = [{"input": e.entrada, "output": e.saida} for e in self.spec.exemplos]
        instrucao = self.spec.instrucao.strip()

        self._instances = [
            TaskInstance(
                id=c.id,
                input=f"{instrucao}\n\n{c.entrada}" if instrucao else c.entrada,
                ground_truth=c.esperado,
                task_type=self.spec.tipo,
                response_format=self.spec.formato_resposta,
                eval_criteria=list(self.spec.criterios),
                metadata={
                    "valid_labels": list(self.spec.rotulos_validos),
                    "examples": exemplos,
                    # Fora do prompt, para leitura do resultado depois.
                    "nota_analise": c.nota,
                    "tarefa_declarativa": True,
                },
            )
            for c in self.spec.casos
        ]

    def score(self, output: str, instance: TaskInstance) -> float:
        """
        Acerto exato do rótulo — a mesma regra das tarefas de classificação
        embutidas, e o teste de equivalência existe para garantir que continue
        sendo a mesma.

        Sem nota parcial: "chegou perto" de um rótulo errado é um erro com
        consequência, não meio acerto.
        """
        esperado = str(instance.ground_truth).strip().lower()
        obtido = (output or "").strip().lower()

        if obtido == esperado:
            return 1.0

        # O modelo às vezes responde com frase; procura o rótulo isolado.
        if re.search(rf"\b{re.escape(esperado)}\b", obtido):
            # Só conta se NENHUM outro rótulo válido aparecer junto — senão a
            # resposta está ambígua, e contá-la como acerto infla o score.
            outros = [r for r in self.spec.rotulos_validos
                      if r.lower() != esperado
                      and re.search(rf"\b{re.escape(r.lower())}\b", obtido)]
            return 1.0 if not outros else 0.0
        return 0.0
