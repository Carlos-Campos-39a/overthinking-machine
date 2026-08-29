# CLAUDE.md — Instruções para o Claude Code

## Sobre o projeto

Replicação do paper "The Geometry of Truth" (Marks & Tegmark, 2024) com extensão
para português brasileiro. O objetivo é de aprendizado — entender mecanisticamente
como LLMs representam verdade/falsidade internamente.

---

## Regras gerais

- Sempre consultar `PLANNING.md` antes de iniciar qualquer sprint
- Trabalhar um sprint de cada vez — não antecipar etapas
- Commits frequentes com mensagens descritivas em português
- Nunca hardcodar caminhos absolutos — usar `pathlib.Path` e caminhos relativos
- Todo código deve rodar do diretório raiz do projeto

---

## Convenções de código

- Python 3.10+
- Type hints em todas as funções públicas
- Docstrings em português (projeto de aprendizado pessoal)
- Funções pequenas e com responsabilidade única
- Sem notebooks para lógica de negócio — lógica vai em `src/`, notebooks só consomem

---

## Sobre o modelo

- Modelo principal: `meta-llama/Llama-3.2-1B` (ou `Llama-3.2-3B`)
- Carregar sempre via TransformerLens: `HookedTransformer.from_pretrained(...)`
- **Nunca** carregar o modelo dentro de funções de dataset ou probe — passar como argumento
- Salvar ativações extraídas em `data/processed/` para evitar recomputação
- Ativações salvas como `.npy` com naming: `{dataset}_{lang}_layer{N}.npy`

---

## Sobre os datasets

Cada dataset é um CSV com colunas obrigatórias:
```
statement  | string | a afirmação completa
label      | int    | 1 = verdadeiro, 0 = falso
lang       | string | "en" ou "pt"
dataset    | string | nome do dataset (ex: "cities", "cidades_br")
```

Datasets EN replicam o paper. Datasets PT são a extensão original.
Manter balanceamento 50/50 entre True e False em todos os datasets.

---

## Sobre os experimentos

### Patching
- Sempre usar formato few-shot (2 exemplos + 1 target) como no paper
- Tokens alvo: "TRUE"/"FALSE" em EN, "VERDADEIRA"/"FALSA" em PT
- Registrar diff = log P(token_true) − log P(token_false)

### Probing
- Layer a usar: identificada no Sprint 3 via patching (grupo b do paper)
- Sempre centrar as ativações antes de probing (subtrair média)
- Reportar acurácia in-distribution E out-of-distribution

### Mass-mean probe
- θ_mm = µ_true − µ_false (diferença de médias)
- Versão IID: p_iid(x) = σ(θ_mm^T Σ^{-1} x)
- Normalizar θ_mm para comparação cross-lingual

---

## Dependências

Ver `requirements.txt`. Instalar com:
```bash
pip install -r requirements.txt
```

Principais:
- `transformer_lens` — extração de ativações
- `transformers` + `torch` — backend do modelo
- `scikit-learn` — LogisticRegression
- `numpy`, `pandas` — manipulação de dados
- `matplotlib`, `seaborn` — visualização

---

## O que NÃO fazer

- Não usar Ollama — precisamos das ativações internas
- Não instalar `bitsandbytes` ainda — começar sem quantização para entender o baseline
- Não rodar Sprint 3+ sem ter os datasets do Sprint 1 validados
- Não modificar datasets após extrair ativações — reextração é cara
