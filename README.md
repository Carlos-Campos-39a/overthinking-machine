# Overthinking Machine — TCC Agent Harness

Combinação experimental dos papers **"Towards a Science of Scaling Agent Systems"** (Kim et al., Google Research/Google DeepMind/MIT, 2025, arXiv:2512.08296) e **"Meta-Harness: End-to-End Optimization of Model Harnesses"** (Lee et al., Stanford/KRAFTON/MIT, 2026, arXiv:2603.28052).

**Pergunta central:** um harness otimizado automaticamente pelo Meta-Harness em um agente único (SAS) supera um sistema multi-agente (MAS) com harness manual?

---

## Os dois papers-base

**Paper 1 — Scaling Agent Systems (Kim et al., 2025)**
Estuda como 5 arquiteturas de multi-agente escalam em performance sobre 180 configurações controladas (Finance-Agent, BrowseComp-Plus, PlanCraft, Workbench). Mostra que a topologia de comunicação entre agentes importa tanto quanto o modelo, com amplificação de erro dependente da arquitetura (Independent 17.2×, Centralized 4.4×) e efeitos task-contingentes (Centralized +80.8% em raciocínio financeiro; todas as variantes MAS degradando -39% a -70% em planejamento sequencial).

**Paper 2 — Meta-Harness (Lee et al., 2026)**
Mostra que o *harness* (código que define o que o modelo vê) pode gerar diferenças grandes de performance no mesmo benchmark. Introduz um loop externo de busca automática de harnesses (Algorithm 1): um proposer agêntico lê o filesystem de candidatos anteriores (código + scores + traces) e propõe código novo a cada iteração, superando ACE (Zhang et al., 2025) e MCE em benchmarks de classificação de texto.

**Apoio teórico complementar:** Cemri et al. (2025), "Why Do Multi-Agent LLM Systems Fail?" (arXiv:2503.13657) — taxonomia MAST de 14 modos de falha em MAS, citada como trabalho relacionado no próprio Kim et al.; Zhang et al. (2025), "Agentic Context Engineering" (ACE, arXiv:2510.04618) e Ye et al. (2026), "Meta Context Engineering" (MCE, arXiv:2601.21557), que fundamentam os harnesses `ace`/`mce` e são usados como baselines de comparação no próprio Lee et al.; Bigeard et al. (2025), "Finance Agent Benchmark" (arXiv:2508.00828), fonte do benchmark Finance-Agent usado em Kim et al.

---

## Arquiteturas de agente (Paper 1)

| Arquitetura | Topologia | Quando usar |
|---|---|---|
| `sas` | 1 agente, 0 overhead | baseline, custo mínimo |
| `independent` | N paralelos, sem comunicação | medir efeito puro de paralelismo |
| `centralized` | orquestrador → workers → síntese | tarefas decomponíveis |
| `decentralized` | debate peer-to-peer all-to-all | alta exploração |
| `hybrid` | hierarquia + debate entre workers | melhor geral |

## Harnesses (Paper 2)

| Harness | Memória | Aprende |
|---|---|---|
| `zero_shot` | nenhuma | não |
| `few_shot` | exemplos estáticos | não |
| `ace` | Knowledge Base `.md` | o **quê** funcionou |
| `mce` | Pokédex de skills `.md` | o **porquê** funcionou |
| `meta_harness` | filesystem completo | código novo por iteração |

`ace` e `mce` acumulam conhecimento **entre execuções** nos diretórios `knowledge_base/` e `pokedex/`.

---

## Estrutura do projeto

```
PROJETO/
├── run.py                  ← CLI principal (Typer + Rich)
├── config.yaml             ← ponto de entrada único
├── overthinking-machine.html ← simulador web local
├── src/
│   ├── llm_factory.py      ← único ponto de criação de LLMs (provider/model)
│   ├── task_base.py        ← TaskInstance, TaskBase, TaskRegistry
│   ├── runner.py           ← orquestrador do experimento
│   ├── agents/
│   │   ├── sas.py
│   │   ├── independent.py
│   │   ├── centralized.py
│   │   ├── decentralized.py
│   │   ├── hybrid.py
│   │   └── agent_factory.py
│   ├── harnesses/
│   │   ├── harness_base.py
│   │   └── manual_harnesses.py  ← zero_shot, few_shot, ace, mce
│   ├── tasks/
│   │   ├── finance_agent.py     ← 15 instâncias, llm_judge
│   │   └── text_classification.py ← 20 instâncias, binary
│   ├── evaluators/
│   │   └── evaluators.py        ← BinaryEvaluator, LLMJudgeEvaluator
│   └── meta_harness/
│       └── meta_harness.py      ← Algorithm 1 do Paper 2
├── runs/                   ← resultados persistidos automaticamente
│   └── candidates/         ← candidatos do Meta-Harness
├── knowledge_base/         ← memória ACE (persiste entre execuções)
└── pokedex/                ← memória MCE (persiste entre execuções)
```

---

## Como rodar

```bash
# 1. Ativar o ambiente virtual
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac/Linux

# 2. Configurar API keys no .env
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

# 3. Rodar com config.yaml padrão
python run.py

# 4. Ou com flags de override
python run.py --model google/gemini-2.0-flash --architecture sas --harness ace --task finance_agent --evaluator llm_judge
python run.py --architecture hybrid --harness mce --task text_classification --evaluator binary
python run.py --harness meta_harness --meta-budget 5

# 5. Listar opções disponíveis
python run.py --list-models
python run.py --list-tasks
python run.py --list-architectures
python run.py --list-harnesses
```

Cada execução salva em `runs/{run_id}/`: `config.json`, `scores.json` e `trace.jsonl`.

---

## Simulador web

Abra `overthinking-machine.html` no navegador. Permite configurar e simular qualquer combinação de arquitetura × harness × tarefa, importar instâncias customizadas via CSV e exportar o modelo de CSV para preencher com seus próprios dados.

---

## Experimentos planejados

| Arquitetura | Harness | Tarefa | Avaliador |
|---|---|---|---|
| sas | zero_shot | finance_agent | llm_judge |
| sas | few_shot | finance_agent | llm_judge |
| sas | ace | finance_agent | llm_judge |
| sas | mce | finance_agent | llm_judge |
| sas | meta_harness | finance_agent | llm_judge |
| centralized | zero_shot | finance_agent | llm_judge |
| centralized | ace | finance_agent | llm_judge |
| centralized | meta_harness | finance_agent | llm_judge |
| hybrid | mce | finance_agent | llm_judge |
| hybrid | meta_harness | finance_agent | llm_judge |
| sas | zero_shot | text_classification | binary |
| sas | few_shot | text_classification | binary |
| sas | ace | text_classification | binary |
| sas | mce | text_classification | binary |
| sas | meta_harness | text_classification | binary |

---

## Stack

Python 3.13 · LangChain · LangGraph · Typer · Rich · PyYAML · Pydantic
