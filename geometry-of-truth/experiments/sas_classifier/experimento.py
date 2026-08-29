"""
experimento.py — Geometria do Acerto em Agentes Classificadores SAS
====================================================================
Extrai ativações do Llama-3.2-1B por camada enquanto um agente
zero-shot classifica afirmações como verdadeiro/falso.
Exporta otm_results.json para visualização na plataforma OTM.

Uso:
    cd geometry-of-truth
    python experiments/sas_classifier/experimento.py
    python experiments/sas_classifier/experimento.py --dataset cidades_br --n 40 --arch sas_zero_shot
"""

import csv
import json
import math
import random
import argparse
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from transformer_lens import HookedTransformer

# ── Caminhos ──────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).parent.parent.parent   # geometry-of-truth/
DATA_DIR  = ROOT / "data" / "raw"
OUT_DIR   = Path(__file__).parent                 # experiments/sas_classifier/

# ── Argumentos ────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--dataset", default="cidades_br",
                    choices=["cities", "neg_cities", "larger_than",
                             "cidades_br", "neg_cidades_br", "traducoes_en_pt"])
parser.add_argument("--n",    type=int, default=40, help="Número de instâncias")
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--arch", default="sas_zero_shot",
                    choices=["sas_zero_shot", "sas_few_shot", "zero_shot_only"])
parser.add_argument("--model", default="meta-llama/Llama-3.2-1B")
args = parser.parse_args()

# ── Prompts por arquitetura ───────────────────────────────────────────────────

FEW_SHOT_EXAMPLES = """Exemplos:
Afirmação: A cidade de São Paulo fica no Brasil. → verdadeiro
Afirmação: A cidade de Buenos Aires fica no Brasil. → falso
Afirmação: A cidade do Rio de Janeiro fica na Argentina. → falso

"""

def build_prompt(statement, arch):
    if arch == "sas_zero_shot":
        return (
            "Você é um classificador preciso. "
            "Classifique a afirmação abaixo como verdadeiro ou falso. "
            "Responda APENAS com 'verdadeiro' ou 'falso', sem mais nada.\n\n"
            f"Afirmação: {statement}\nResposta:"
        )
    elif arch == "sas_few_shot":
        return (
            "Você é um classificador preciso. "
            "Classifique a afirmação abaixo como verdadeiro ou falso. "
            "Responda APENAS com 'verdadeiro' ou 'falso', sem mais nada.\n\n"
            + FEW_SHOT_EXAMPLES
            + f"Afirmação: {statement}\nResposta:"
        )
    else:  # zero_shot_only
        return f"Afirmação: {statement}\nVerdadeiro ou falso?"

# ── 1. Carrega modelo ─────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"  Geometria do Acerto — {args.arch}")
print(f"  Dataset: {args.dataset} | N: {args.n} | Modelo: {args.model}")
print(f"{'='*60}\n")

print("Carregando modelo...")
model = HookedTransformer.from_pretrained(args.model)
print(f"✓ Modelo carregado: {model.cfg.n_layers} camadas, d_model={model.cfg.d_model}\n")

# ── 2. Carrega dataset ────────────────────────────────────────────────────────

def load_dataset(name, n, seed):
    path = DATA_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Dataset não encontrado: {path}")
    random.seed(seed)
    rows = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({"statement": row["statement"], "label": int(row["label"])})
    true_rows  = [r for r in rows if r["label"] == 1]
    false_rows = [r for r in rows if r["label"] == 0]
    sample = (random.sample(true_rows,  min(n // 2, len(true_rows))) +
              random.sample(false_rows, min(n // 2, len(false_rows))))
    random.shuffle(sample)
    return sample

sample = load_dataset(args.dataset, args.n, args.seed)
print(f"✓ {len(sample)} instâncias carregadas ({sum(r['label'] for r in sample)} verdadeiras)\n")

# ── 3. Classifica + extrai ativações ─────────────────────────────────────────

def classify_and_extract(model, statement, label, arch):
    prompt = build_prompt(statement, arch)
    tokens = model.to_tokens(prompt)
    activations = {}

    hooks = [
        (f"blocks.{l}.hook_resid_post",
         lambda value, hook, l=l: activations.update(
             {l: value[0, -1, :].detach().cpu().float().numpy()}
         ))
        for l in range(model.cfg.n_layers)
    ]

    with model.hooks(fwd_hooks=hooks):
        logits = model(tokens)

    next_tok = model.to_string([logits[0, -1, :].argmax().item()]).strip().lower()
    pred = 1 if ("verdadeiro" in next_tok or "true" in next_tok) else 0

    return {
        "statement": statement,
        "label":     label,
        "pred":      pred,
        "correct":   pred == label,
        "activations": [activations[l].tolist() for l in range(model.cfg.n_layers)],
    }

print("Classificando instâncias e extraindo ativações...")
results = []
for i, row in enumerate(sample):
    r = classify_and_extract(model, row["statement"], row["label"], args.arch)
    results.append(r)
    acc = sum(x["correct"] for x in results) / len(results)
    print(f"  [{i+1:02d}/{len(sample)}] {'✓' if r['correct'] else '✗'}  "
          f"acurácia: {acc:.1%}  |  {row['statement'][:55]}...")

n_correct   = sum(1 for r in results if r["correct"])
agent_acc   = n_correct / len(results)
print(f"\n✓ Classificação concluída — acurácia final: {agent_acc:.1%}\n")

# ── 4. PCA 2D + sondas lineares por camada ───────────────────────────────────

print("Calculando PCA 2D e sondas lineares por camada...")
n_layers   = model.cfg.n_layers
pca_layers = []
probe_accs = []

for layer in range(n_layers):
    acts   = np.array([r["activations"][layer] for r in results])
    labels = np.array([1 if r["correct"] else 0 for r in results])

    # PCA 2D
    proj = PCA(n_components=2).fit_transform(acts)
    pca_layers.append([{
        "x":         round(float(proj[i, 0]), 6),
        "y":         round(float(proj[i, 1]), 6),
        "correct":   bool(results[i]["correct"]),
        "label":     int(results[i]["label"]),
        "statement": results[i]["statement"][:80],
    } for i in range(len(results))])

    # Sonda linear
    acc = LogisticRegression(max_iter=300, C=10).fit(acts, labels).score(acts, labels)
    probe_accs.append(round(float(acc), 4))
    bar = "█" * int(acc * 20)
    print(f"  Camada {layer:02d} — sonda: {acc:.1%}  {bar}")

# ── 5. Métricas finais ────────────────────────────────────────────────────────

best    = probe_accs.index(max(probe_accs))
corr_x  = [p["x"] for p in pca_layers[best] if p["correct"]]
incorr_x = [p["x"] for p in pca_layers[best] if not p["correct"]]
sep = (abs(sum(corr_x)/len(corr_x) - sum(incorr_x)/len(incorr_x))
       if corr_x and incorr_x else 0.0)

# ── 6. Exporta JSON para OTM ──────────────────────────────────────────────────

export = {
    "n_instances":      len(results),
    "n_correct":        n_correct,
    "n_incorrect":      len(results) - n_correct,
    "agent_accuracy":   round(agent_acc, 4),
    "n_layers":         n_layers,
    "d_model":          model.cfg.d_model,
    "pca_layers":       pca_layers,
    "probe_accuracies": probe_accs,
    "best_probe_layer": best,
    "best_probe_acc":   round(max(probe_accs), 4),
    "pc1_separation":   round(sep, 4),
    "dataset":          args.dataset,
    "arch":             args.arch,
    "mode":             "real",
}

out_path = OUT_DIR / f"otm_results_{args.dataset}_{args.arch}.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(export, f, ensure_ascii=False, indent=2)

print(f"\n{'='*60}")
print(f"  ✓ Exportado: {out_path.name}")
print(f"  Acurácia do agente : {agent_acc:.1%}")
print(f"  Melhor camada      : {best} — sonda: {max(probe_accs):.1%}")
print(f"  Separação PC1      : {sep:.3f}")
print(f"{'='*60}")
print(f"\n  Importe o arquivo na plataforma OTM:")
print(f"  {out_path}")
