# Geometry of Truth — Plano de Trabalho

Replicação e extensão do paper "The Geometry of Truth" (Marks & Tegmark, 2024)
com foco em comparação inglês vs. português brasileiro.

---

## Objetivo

Investigar se LLMs representam linearmente a verdade/falsidade de afirmações factuais,
replicando os experimentos do paper original e estendendo para PT-BR como contribuição nova.

**Pergunta central da extensão:** A direção de verdade aprendida em inglês generaliza
para português? O vetor θ_mm treinado em EN consegue classificar e intervir em
afirmações PT-BR?

---

## Stack técnica

- **Modelo:** LLaMA-3.2-1B (ou 3B se houver RAM suficiente) via HuggingFace
- **Extração de ativações:** TransformerLens — `run_with_cache()`, `logit_lens`
- **Probing:** scikit-learn (LogisticRegression) + implementação manual de mass-mean
- **Visualização:** matplotlib, seaborn
- **Ambiente:** Python 3.10+, gerenciado via venv local

---

## Estrutura de pastas

```
geometry-of-truth/
├── PLANNING.md          ← este arquivo
├── CLAUDE.md            ← instruções para o Claude Code
├── requirements.txt
├── data/
│   ├── raw/             ← datasets brutos (CSV)
│   └── processed/       ← activações extraídas (numpy/pt)
├── src/
│   ├── datasets.py      ← construção dos datasets EN e PT
│   ├── model.py         ← carregamento do modelo e extração de ativações
│   ├── patching.py      ← experimentos de patching causal
│   ├── probing.py       ← LR probe e mass-mean probe
│   └── viz.py           ← PCA e visualizações
├── notebooks/
│   └── exploration.ipynb
└── outputs/
    ├── figures/
    ├── probes/
    └── patching/
```

---

## Sprints

### Sprint 1 — Datasets (sem GPU, sem modelo)
**Objetivo:** Ter os datasets EN e PT prontos em CSV, validados manualmente.

Tarefas:
- [ ] `src/datasets.py` — classe `TrueFalseDataset` com método `build()`
- [ ] Dataset EN: `cities` (~300 pares), `larger_than` (~200 pares)
- [ ] Dataset EN: `neg_cities` (negações com "not")
- [ ] Dataset PT: `cidades_br` (~300 pares) — "A cidade de [X] fica no/na [estado]."
- [ ] Dataset PT: `traducoes_en_pt` — "A palavra em inglês '[X]' significa '[Y]'."
- [ ] Dataset PT: `neg_cidades_br` (negações com "não")
- [ ] Script de validação: checar balanceamento True/False, ausência de ambiguidade

Entregável: `data/raw/*.csv` com colunas `statement`, `label` (1=true, 0=false), `lang`, `dataset`

---

### Sprint 2 — Modelo e extração de ativações
**Objetivo:** Carregar LLaMA via TransformerLens e extrair residual stream.

Tarefas:
- [ ] `src/model.py` — wrapper para carregar modelo com TransformerLens
- [ ] Testar `model.run_with_cache()` em uma frase simples
- [ ] Identificar token position correta (último token da frase / ponto final)
- [ ] Função `get_activations(statements, layer)` → tensor [n, d_model]
- [ ] Salvar ativações em `data/processed/` para não recomputar
- [ ] Confirmar que d_model bate com o esperado para o modelo escolhido

Entregável: `data/processed/{dataset_name}_layer{N}_acts.npy`

---

### Sprint 3 — Patching causal
**Objetivo:** Replicar Fig. 2 do paper — heatmap de causalidade por token/camada.

Tarefas:
- [ ] `src/patching.py` — setup do prompt few-shot pF / pT
- [ ] Loop: para cada (token_pos, layer), fazer swap de ativação pF → pT
- [ ] Registrar diff log P(TRUE) − log P(FALSE) após cada swap
- [ ] Gerar heatmap EN (replicação da Fig. 2)
- [ ] Adaptar prompt few-shot para PT-BR
- [ ] Gerar heatmap PT — comparar grupos causais com EN

Entregável: `outputs/patching/heatmap_en.png`, `outputs/patching/heatmap_pt.png`

---

### Sprint 4 — PCA e probing
**Objetivo:** Replicar Fig. 1 do paper e treinar probes.

Tarefas:
- [ ] `src/viz.py` — PCA 2D por dataset, colorindo True vs False
- [ ] Replicar Fig. 1: visualização EN cities, sp_en_trans, larger_than
- [ ] Visualização PT: cidades_br, traducoes_en_pt
- [ ] `src/probing.py` — LogisticRegression probe
- [ ] `src/probing.py` — mass-mean probe (θ_mm = µ+ − µ−, versão IID)
- [ ] Tabela de acurácia: treinar em EN, testar em PT (cross-lingual)
- [ ] Medir cosine similarity entre direção EN e direção PT

Entregável: `outputs/figures/pca_*.png`, `outputs/probes/accuracy_table.csv`

---

### Sprint 5 — Intervenção causal cross-lingual (contribuição nova)
**Objetivo:** Usar θ_mm treinado em EN para intervir em afirmações PT.

Tarefas:
- [ ] Pegar θ_mm do probe treinado em `cities` (EN)
- [ ] Aplicar intervenção: x_pt_false + θ_mm → checar se modelo classifica como TRUE
- [ ] Calcular NIE (Normalized Indirect Effect) para false→true e true→false
- [ ] Comparar com NIE do paper (Tabela 2) como baseline
- [ ] Análise: a direção de verdade é language-agnostic?

Entregável: `outputs/patching/nie_crosslingual.csv`, seção de análise no notebook

---

### Sprint 6 — Documentação
- [ ] Notebook final `notebooks/exploration.ipynb` com pipeline completo
- [ ] README.md com instruções de reprodução
- [ ] Comparação sistemática EN vs PT nos principais achados

---

## Referências

- Paper: https://arxiv.org/abs/2310.06824
- Repositório original: https://github.com/saprmarks/geometry-of-truth
- TransformerLens docs: https://transformerlensorg.github.io/TransformerLens/
- LLaMA-3.2 HuggingFace: https://huggingface.co/meta-llama/Llama-3.2-1B
