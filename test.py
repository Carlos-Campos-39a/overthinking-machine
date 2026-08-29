from dotenv import load_dotenv
load_dotenv()

from src.task_base import TaskInstance

inst = TaskInstance(
    id="teste_001",
    input="Analise o impacto da alta do dólar no setor de varejo.",
    ground_truth={"criterios": ["impacto nos custos", "margens", "repasse ao consumidor"]},
    task_type="market_search",
    response_format="long_prose",
    eval_criteria=["accuracy"],
)

print(f"id: {inst.id}")
print(f"task_type: {inst.task_type}")
print(f"response_format: {inst.response_format}")
print(f"eval_criteria: {inst.eval_criteria}")
print()
print("prompt_for_judge:")
from src.task_base import TaskBase

# Mostra como o juiz vai receber essa instância
class _Dummy(TaskBase):
    name = "_dummy"
    def load(self): pass
    def score(self, o, i): return 0.0

print(_Dummy().prompt_for_judge("O dólar alto encarece importações...", inst))