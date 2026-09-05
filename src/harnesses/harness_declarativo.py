"""
harness_declarativo.py — monta mensagens a partir de uma EspecHarness.

Reusa `_system()` e `_fmt()` de manual_harnesses por dois motivos que não são
estéticos:

  _system  honra instance.metadata["system_override"], que é como o módulo 3
           (sensibilidade de prompt) roda a mesma tarefa com variações do
           system para medir a contribuição de cada cláusula. Um harness que
           montasse o system por conta própria quebraria essa ablação em
           silêncio.

  _fmt     injeta os rótulos válidos no prompt. Sem isso o modelo inventa o
           formato da resposta, e o avaliador passa a medir formatação em vez
           de capacidade — exatamente o erro que a plataforma existe para
           evitar.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.topologia_spec import renderizar
from src.harnesses.harness_base import HarnessBase, HarnessOutput
from src.harnesses.harness_spec import EspecHarness, validar_harness
from src.harnesses.manual_harnesses import _fmt, _system
from src.task_base import TaskInstance


class HarnessDeclarativo(HarnessBase):
    """Harness definido por especificação, sem código."""

    def __init__(self, spec: EspecHarness | dict):
        self.spec = validar_harness(spec)
        self.name = self.spec.nome

    def build_messages(self, instance: TaskInstance) -> HarnessOutput:
        contexto = {
            "input":               instance.input,
            "format_instructions": _fmt(instance),
            "exemplos":            self._montar_exemplos(instance),
            "task_type":           instance.task_type,
            "id":                  instance.id,
            "rotulos_validos":     ", ".join(instance.metadata.get("valid_labels", []) or []),
        }

        return HarnessOutput(
            messages=[
                SystemMessage(content=self._system(instance, contexto)),
                HumanMessage(content=renderizar(self.spec.humano, contexto)),
            ],
            metadata={
                "harness":     self.name,
                "task_type":   instance.task_type,
                "declarativo": True,
            },
        )

    def _system(self, instance: TaskInstance, contexto: dict) -> str:
        # A ablação de prompt tem precedência sobre o system da especificação:
        # se o módulo 3 está medindo o efeito de remover uma cláusula, é a
        # versão dele que precisa chegar ao modelo.
        if instance.metadata.get("system_override") is not None:
            return _system(instance)
        if self.spec.system is not None:
            return renderizar(self.spec.system, contexto)
        return _system(instance)

    def _montar_exemplos(self, instance: TaskInstance) -> str:
        if self.spec.exemplos == 0:
            return ""
        disponiveis = instance.metadata.get("examples") or []
        # None = todos; um inteiro corta.
        exemplos = disponiveis if self.spec.exemplos is None else disponiveis[: self.spec.exemplos]
        if not exemplos:
            return ""
        corpo = "".join(
            renderizar(self.spec.formato_exemplo, {
                "i": i,
                "entrada": ex.get("input", ""),
                "saida": ex.get("output", ""),
            })
            for i, ex in enumerate(exemplos, 1)
        )
        return renderizar(self.spec.bloco_exemplos, {"exemplos": corpo})
