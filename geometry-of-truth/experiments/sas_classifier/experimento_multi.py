"""
experimento_multi.py — Geometria do Acerto: múltiplos datasets
===============================================================
Roda o pipeline de extração de ativações em datasets HuggingFace
variados, permitindo validação cruzada da hipótese geométrica.

Datasets suportados:
  ag_news      — 4 classes: World / Sports / Business / Sci-Tech
  imdb         — 2 classes: negativo / positivo  (sentimento)
  sst2         — 2 classes: negativo / positivo  (sentimento, frases curtas)
  trec         — 6 classes: tipo de pergunta
  yahoo_topics — 10 classes: tópicos Yahoo Answers

Uso no Kaggle (rodar célula a célula — veja instruções):
  dataset = "imdb"
  exec(open("experimento_multi.py").read())

Ou via argparse:
  python experimento_multi.py --dataset imdb --n 40
  python experimento_multi.py --dataset trec --n 60 --arch sas_few_shot
"""

import json, random, argparse, sys
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from transformer_lens import HookedTransformer

# ── Argumentos (ignorados se variáveis já definidas no notebook) ──────────────

if "dataset" not in dir() and "dataset" not in globals():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="imdb",
                        choices=["ag_news","imdb","sst2","trec","yahoo_topics"])
    parser.add_argument("--n",    type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--arch", default="sas_zero_shot",
                        choices=["sas_zero_shot","sas_few_shot","zero_shot_only"])
    parser.add_argument("--model", default="meta-llama/Llama-3.2-1B")
    parser.add_argument("--out_dir", default=".")
    args = parser.parse_args()
    DATASET  = args.dataset
    N        = args.n
    SEED     = args.seed
    ARCH     = args.arch
    MODEL_ID = args.model
    OUT_DIR  = Path(args.out_dir)
else:
    # Valores definidos externamente (célula de notebook)
    DATASET  = globals().get("dataset",  "imdb")
    N        = globals().get("n",        100)
    SEED     = globals().get("seed",     42)
    ARCH     = globals().get("arch",     "sas_zero_shot")
    MODEL_ID = globals().get("model_id", "meta-llama/Llama-3.2-1B")
    OUT_DIR  = Path(globals().get("out_dir", "/kaggle/working"))

# ── Registro de datasets ──────────────────────────────────────────────────────

DATASETS = {
    "ag_news": {
        "hf_name": "ag_news", "hf_split": "test",
        "text_col": "text", "label_col": "label",
        "n_classes": 4,
        "label_names": ["World", "Sports", "Business", "Sci/Tech"],
        "label_names_pt": ["mundo", "esportes", "negócios", "tecnologia"],
        "task": "topico",
        "zs_instruction": (
            "Você é um classificador de notícias. "
            "Classifique a notícia abaixo em uma das categorias: "
            "mundo, esportes, negócios ou tecnologia. "
            "Responda APENAS com uma dessas palavras."
        ),
        "fs_examples": (
            "Exemplos:\n"
            "Notícia: Brazil wins the World Cup final. → esportes\n"
            "Notícia: Fed raises interest rates by 0.5%. → negócios\n"
            "Notícia: New telescope discovers distant galaxy. → tecnologia\n\n"
        ),
        "input_label": "Notícia",
        "parse": lambda t: (
            0 if any(w in t for w in ["world","mundo","mundial"]) else
            1 if any(w in t for w in ["sport","esporte","futebol"]) else
            2 if any(w in t for w in ["business","negócio","finan","econom"]) else
            3 if any(w in t for w in ["tech","tecnolog","sci","ciência","ciência"]) else -1
        ),
    },
    "imdb": {
        "hf_name": "imdb", "hf_split": "test",
        "text_col": "text", "label_col": "label",
        "n_classes": 2,
        "label_names": ["Negative", "Positive"],
        "label_names_pt": ["negativo", "positivo"],
        "task": "sentimento",
        "zs_instruction": (
            "Você é um classificador de sentimento. "
            "Classifique a crítica de filme abaixo como positivo ou negativo. "
            "Responda APENAS com 'positivo' ou 'negativo'."
        ),
        "fs_examples": (
            "Exemplos:\n"
            "Crítica: This film was absolutely wonderful, I loved every scene. → positivo\n"
            "Crítica: Terrible movie, waste of time, boring and predictable. → negativo\n\n"
        ),
        "input_label": "Crítica",
        "parse": lambda t: (
            1 if any(w in t for w in ["positivo","positive","pos","great","good","excellent"]) else
            0 if any(w in t for w in ["negativo","negative","neg","bad","poor","terrible"]) else -1
        ),
    },
    "sst2": {
        "hf_name": "glue", "hf_config": "sst2", "hf_split": "validation",
        "text_col": "sentence", "label_col": "label",
        "n_classes": 2,
        "label_names": ["Negative", "Positive"],
        "label_names_pt": ["negativo", "positivo"],
        "task": "sentimento",
        "zs_instruction": (
            "Você é um classificador de sentimento. "
            "Classifique a frase abaixo como positivo ou negativo. "
            "Responda APENAS com 'positivo' ou 'negativo'."
        ),
        "fs_examples": (
            "Exemplos:\n"
            "Frase: the film is bright and hopeful. → positivo\n"
            "Frase: it is a dull and lifeless film. → negativo\n\n"
        ),
        "input_label": "Frase",
        "parse": lambda t: (
            1 if any(w in t for w in ["positivo","positive","pos"]) else
            0 if any(w in t for w in ["negativo","negative","neg"]) else -1
        ),
    },
    "trec": {
        "hf_name": "trec", "hf_split": "test",
        "text_col": "text", "label_col": "coarse_label",
        "n_classes": 6,
        "label_names": ["ABBR","ENTY","DESC","HUM","LOC","NUM"],
        "label_names_pt": ["abreviação","entidade","descrição","pessoa","local","número"],
        "task": "tipo_pergunta",
        "zs_instruction": (
            "Você é um classificador de perguntas. "
            "Classifique o tipo da pergunta abaixo escolhendo entre: "
            "abreviação, entidade, descrição, pessoa, local ou número. "
            "Responda APENAS com uma dessas palavras."
        ),
        "fs_examples": (
            "Exemplos:\n"
            "Pergunta: What does NASA stand for? → abreviação\n"
            "Pergunta: Who invented the telephone? → pessoa\n"
            "Pergunta: What is the capital of France? → local\n"
            "Pergunta: How many planets are in the solar system? → número\n\n"
        ),
        "input_label": "Pergunta",
        "parse": lambda t: (
            0 if any(w in t for w in ["abreviação","abbreviation","abbr"]) else
            1 if any(w in t for w in ["entidade","entity","enty"]) else
            2 if any(w in t for w in ["descrição","description","desc"]) else
            3 if any(w in t for w in ["pessoa","person","human","hum"]) else
            4 if any(w in t for w in ["local","location","loc","place","cidade","país"]) else
            5 if any(w in t for w in ["número","number","num","quantidade"]) else -1
        ),
    },
    "yahoo_topics": {
        "hf_name": "yahoo_answers_topics", "hf_split": "test",
        "text_col": "question_title", "label_col": "topic",
        "n_classes": 10,
        "label_names": [
            "Society","Science","Health","Education","Computers",
            "Sports","Business","Entertainment","Relationships","Politics"
        ],
        "label_names_pt": [
            "sociedade","ciência","saúde","educação","computadores",
            "esportes","negócios","entretenimento","relacionamentos","política"
        ],
        "task": "topico",
        "zs_instruction": (
            "Você é um classificador de tópicos. "
            "Classifique a pergunta abaixo escolhendo entre: "
            "sociedade, ciência, saúde, educação, computadores, "
            "esportes, negócios, entretenimento, relacionamentos ou política. "
            "Responda APENAS com uma dessas palavras."
        ),
        "fs_examples": (
            "Exemplos:\n"
            "Pergunta: How do vaccines work? → saúde\n"
            "Pergunta: What is the best programming language? → computadores\n"
            "Pergunta: How do I invest in stocks? → negócios\n\n"
        ),
        "input_label": "Pergunta",
        "parse": lambda t: next(
            (i for i, name in enumerate([
                "sociedade","ciência","saúde","educação","computadores",
                "esportes","negócios","entretenimento","relacionamentos","política",
                "society","science","health","education","computer",
                "sport","business","entertainment","relationship","politic"
            ]) if name in t),
            -1
        ) % 10 if any(name in t for name in [
            "sociedade","ciência","saúde","educação","computadores",
            "esportes","negócios","entretenimento","relacionamentos","política",
            "society","science","health","education","computer",
            "sport","business","entertainment","relationship","politic"
        ]) else -1,
    },
}

cfg = DATASETS[DATASET]

# ── Print inicial ─────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"  Geometria do Acerto — {ARCH}")
print(f"  Dataset: {DATASET} ({cfg['n_classes']} classes) | N: {N}")
print(f"  Tarefa: {cfg['task']} | Modelo: {MODEL_ID}")
print(f"{'='*60}\n")

# ── 1. Carrega modelo (reutiliza se já existir na memória) ────────────────────

if "model" not in globals() or model is None:
    print("Carregando modelo...")
    from transformer_lens import HookedTransformer
    model = HookedTransformer.from_pretrained(MODEL_ID, device="cpu")
    print(f"✓ Modelo: {model.cfg.n_layers} camadas, d_model={model.cfg.d_model}\n")
else:
    print(f"✓ Modelo já carregado ({model.cfg.n_layers} camadas)\n")

# ── 2. Carrega dataset via HuggingFace ────────────────────────────────────────

print(f"Carregando dataset {DATASET}...")
from datasets import load_dataset as hf_load

hf_args = [cfg["hf_name"]]
hf_kwargs = {"split": cfg["hf_split"]}
if "hf_config" in cfg:
    hf_args.append(cfg["hf_config"])

ds = hf_load(*hf_args, **hf_kwargs)
random.seed(SEED)

# Amostra balanceada por classe
per_class = N // cfg["n_classes"]
rows = []
for cls in range(cfg["n_classes"]):
    cls_rows = [r for r in ds if r[cfg["label_col"]] == cls]
    sample_cls = random.sample(cls_rows, min(per_class, len(cls_rows)))
    for r in sample_cls:
        text = str(r[cfg["text_col"]])[:300]   # trunca textos longos
        rows.append({"statement": text, "label": cls})

random.shuffle(rows)
print(f"✓ {len(rows)} instâncias ({per_class} por classe)\n")

# ── 3. Prompts ────────────────────────────────────────────────────────────────

def build_prompt(text, arch):
    instruction = cfg["zs_instruction"]
    label_pt    = cfg["input_label"]
    if arch == "sas_few_shot":
        return instruction + "\n\n" + cfg["fs_examples"] + f"{label_pt}: {text}\nResposta:"
    elif arch == "zero_shot_only":
        cats = ", ".join(cfg["label_names_pt"])
        return f"{label_pt}: {text}\nCategorias: {cats}. Categoria:"
    else:  # sas_zero_shot
        return instruction + f"\n\n{label_pt}: {text}\nResposta:"

# ── 4. Classifica + extrai ativações ─────────────────────────────────────────

parse_fn = cfg["parse"]

def classify_and_extract(statement, true_label):
    prompt      = build_prompt(statement, ARCH)
    tokens      = model.to_tokens(prompt)
    activations = {}

    hooks = [
        (f"blocks.{l}.hook_resid_post",
         lambda v, hook, l=l: activations.update(
             {l: v[0, -1, :].detach().cpu().float().numpy()}
         ))
        for l in range(model.cfg.n_layers)
    ]

    with model.hooks(fwd_hooks=hooks):
        logits = model(tokens)

    raw   = model.to_string([logits[0, -1, :].argmax().item()]).strip().lower()
    pred  = parse_fn(raw)
    if pred == -1:
        pred = int(logits[0, -1, :].argmax().item()) % cfg["n_classes"]

    return {
        "statement":   statement,
        "label":       true_label,
        "label_name":  cfg["label_names"][true_label],
        "pred":        pred,
        "pred_name":   cfg["label_names"][pred] if 0 <= pred < cfg["n_classes"] else "?",
        "correct":     pred == true_label,
        "raw_token":   raw[:20],
        "activations": [activations[l].tolist() for l in range(model.cfg.n_layers)],
    }

print("Classificando e extraindo ativações...")
results = []
for i, row in enumerate(rows):
    r = classify_and_extract(row["statement"], row["label"])
    results.append(r)
    acc = sum(x["correct"] for x in results) / len(results)
    true_lbl = cfg["label_names"][row["label"]]
    pred_lbl = r["pred_name"]
    mark = "✓" if r["correct"] else "✗"
    print(f"  [{i+1:02d}/{len(rows)}] {mark}  {true_lbl:12s} → {pred_lbl:12s} "
          f"| acc: {acc:.1%}  | {row['statement'][:45]}...")

n_correct = sum(1 for r in results if r["correct"])
agent_acc = n_correct / len(results)
print(f"\n✓ Acurácia final: {agent_acc:.1%}  "
      f"({n_correct}/{len(results)} corretas)\n")

# ── 5. PCA 2D + sondas lineares (in-sample + cross-validation) ───────────────

print("Calculando PCA + sondas lineares por camada...")
print(f"  Método: 5-fold stratified CV  (N={len(results)}, d_model={model.cfg.d_model})\n")

n_layers      = model.cfg.n_layers
pca_layers    = []
probe_accs    = []   # in-sample (referência)
probe_accs_cv = []   # cross-validated (métrica válida)

# Número de folds: mínimo entre 5 e (menor classe // 1)
n_correct_total   = sum(1 for r in results if r["correct"])
n_incorrect_total = len(results) - n_correct_total
min_class = min(n_correct_total, n_incorrect_total)
N_FOLDS   = min(5, max(2, min_class))   # nunca menos de 2 folds

cv = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=42)

for layer in range(n_layers):
    acts   = np.array([r["activations"][layer] for r in results])
    labels = np.array([1 if r["correct"] else 0 for r in results])

    # PCA 2D
    proj = PCA(n_components=2).fit_transform(acts)
    pca_layers.append([{
        "x":          round(float(proj[i, 0]), 6),
        "y":          round(float(proj[i, 1]), 6),
        "correct":    bool(results[i]["correct"]),
        "label":      int(results[i]["label"]),
        "label_name": results[i]["label_name"],
        "statement":  results[i]["statement"][:80],
    } for i in range(len(results))])

    # Sonda in-sample (para referência histórica)
    clf = LogisticRegression(max_iter=300, C=1)
    acc_is = clf.fit(acts, labels).score(acts, labels)
    probe_accs.append(round(float(acc_is), 4))

    # Sonda cross-validated (métrica válida out-of-sample)
    cv_scores = cross_val_score(
        LogisticRegression(max_iter=300, C=1),
        acts, labels, cv=cv, scoring='accuracy'
    )
    acc_cv = float(cv_scores.mean())
    probe_accs_cv.append(round(acc_cv, 4))

    bar_is = "█" * int(acc_is * 20)
    bar_cv = "░" * int(acc_cv * 20)
    print(f"  Camada {layer:02d} — in-sample: {acc_is:.1%} {bar_is}")
    print(f"           CV ({N_FOLDS}-fold): {acc_cv:.1%} {bar_cv}")

# ── 6. Métricas finais ────────────────────────────────────────────────────────

# Melhor camada pela métrica CV (mais conservadora e válida)
best_cv  = probe_accs_cv.index(max(probe_accs_cv))
best_is  = probe_accs.index(max(probe_accs))

corr_x   = [p["x"] for p in pca_layers[best_cv] if p["correct"]]
incorr_x = [p["x"] for p in pca_layers[best_cv] if not p["correct"]]
sep = (abs(sum(corr_x)/len(corr_x) - sum(incorr_x)/len(incorr_x))
       if corr_x and incorr_x else 0.0)

# ── 7. Exporta JSON para OTM ──────────────────────────────────────────────────

export = {
    "n_instances":         len(results),
    "n_correct":           n_correct,
    "n_incorrect":         len(results) - n_correct,
    "agent_accuracy":      round(agent_acc, 4),
    "n_layers":            n_layers,
    "d_model":             model.cfg.d_model,
    "pca_layers":          pca_layers,
    "probe_accuracies":    probe_accs,        # in-sample (referência)
    "probe_accuracies_cv": probe_accs_cv,     # cross-validated (válido)
    "cv_folds":            N_FOLDS,
    "best_probe_layer":    best_cv,
    "best_probe_acc":      round(max(probe_accs_cv), 4),
    "best_probe_acc_is":   round(max(probe_accs), 4),
    "pc1_separation":      round(sep, 4),
    "dataset":             DATASET,
    "arch":                ARCH,
    "task":                cfg["task"],
    "n_classes":           cfg["n_classes"],
    "label_names":         cfg["label_names"],
    "mode":                "real",
}

out_path = OUT_DIR / f"otm_results_{DATASET}_{ARCH}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(export, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"  ✓ Exportado : {out_path}")
print(f"  Acurácia agente : {agent_acc:.1%}  (baseline: {100/cfg['n_classes']:.0f}%)")
print(f"  Melhor sonda CV : camada {best_cv} — {max(probe_accs_cv):.1%}")
print(f"  Melhor sonda IS : camada {best_is} — {max(probe_accs):.1%}")
print(f"  Diferença IS-CV : {max(probe_accs)-max(probe_accs_cv):.1%}  (estimativa de overfitting)")
print(f"  Separação PC1   : {sep:.4f}")
print(f"{'='*60}\n")
print("  Baixe o arquivo em: Kaggle → Output (pasta lateral) → Download")
