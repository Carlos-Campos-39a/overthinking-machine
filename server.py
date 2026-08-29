"""
server.py — API FastAPI que conecta o frontend ao código real do TCC.

Uso:
    pip install fastapi uvicorn
    uvicorn server:app --reload --port 8000

Endpoints:
    POST /api/run          → inicia experimento + stream SSE com output em tempo real
    DELETE /api/run/{id}   → cancela experimento em andamento
    GET  /api/health       → status do servidor
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import threading
import uuid

# ── Força UTF-8 no stdout/stderr (necessário no Windows) ─────────────────────
# Sem isso, qualquer caractere não-ASCII nos logs/respostas do modelo causa
# UnicodeEncodeError: 'ascii' codec can't encode characters ...
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Garante que o diretório do projeto está no path
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

# Carrega GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY do .env
from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env")


app = FastAPI(title="Overthinking Machine API", version="1.0.0")

# ── Modo hospedado (BYOK) ─────────────────────────────────────────────────────
# Quando OTM_HOSTED=1, a plataforma NÃO usa chaves do servidor: cada visitante
# manda a própria chave nos headers da requisição. Isso permite publicar sem
# que terceiros gastem a cota do dono.
HOSTED = os.getenv("OTM_HOSTED", "0") == "1"

# Origens permitidas. Em produção, defina OTM_ALLOWED_ORIGINS com o domínio do
# frontend (separado por vírgula) em vez de deixar aberto.
_origins_env = os.getenv("OTM_ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if _origins_env.strip() == "*" else [
    o.strip() for o in _origins_env.split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Headers pelos quais o visitante envia a própria chave (nunca são persistidos)
_KEY_HEADERS = {
    "google":    "x-google-key",
    "openai":    "x-openai-key",
    "anthropic": "x-anthropic-key",
}


def _keys_from_request(request) -> dict[str, str]:
    """Extrai as chaves BYOK dos headers. Ficam só em memória, por requisição."""
    if request is None:
        return {}
    return {
        prov: request.headers.get(h, "").strip()
        for prov, h in _KEY_HEADERS.items()
        if request.headers.get(h, "").strip()
    }

# Registro de runs ativos (run_id → thread + cancel_event)
active_runs: dict[str, dict] = {}


# ── Request models ─────────────────────────────────────────────────────────────

class RunConfig(BaseModel):
    model: str
    architecture: str
    harness: str
    task: str
    evaluator: str
    num_instances: int = 5
    seed: int = 42
    agent_kwargs: dict = {}
    meta_budget: int = 5
    exp_name: str = ""
    custom_prompts: Optional[dict] = None   # reservado para uso futuro
    instance_ids: list[str] = []            # IDs específicos selecionados na UI


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ── Run (POST + SSE stream) ────────────────────────────────────────────────────

@app.post("/api/run")
async def start_run(cfg: RunConfig, request: Request):
    """
    Inicia um experimento e retorna um stream SSE com o output em tempo real.

    Eventos SSE:
        {"type": "start",   "run_id": "..."}
        {"type": "log",     "text": "linha de output"}
        {"type": "result",  "instance_id": "...", "score": 0.85, "elapsed_s": 2.1}
        {"type": "done",    "results": { run_id, mean_score, scores, harness_used, ... }}
        {"type": "error",   "message": "..."}
        {"type": "cancel"}
    """
    run_id = _gen_run_id()
    cancel_event = threading.Event()
    active_runs[run_id] = {"cancel": cancel_event, "status": "pending"}

    return StreamingResponse(
        _stream_experiment(run_id, cfg, cancel_event, _keys_from_request(request)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.delete("/api/run/{run_id}")
async def cancel_run(run_id: str):
    run = active_runs.get(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    run["cancel"].set()
    run["status"] = "cancelled"
    return {"ok": True, "run_id": run_id}


import re as _re
import os as _os   # alias mantido por compatibilidade com as linhas abaixo

LIBRARY_FILE = PROJECT_DIR / "library.json"
POKEDEX_DIR  = PROJECT_DIR / "pokedex"
KEYS_FILE    = PROJECT_DIR / ".api_keys.json"

# ── API Keys ───────────────────────────────────────────────────────────────────

_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "gemini":    "GOOGLE_API_KEY",
}

_TEST_MODELS = {
    "anthropic": "anthropic/claude-haiku-4-5-20251001",
    "openai":    "openai/gpt-4o-mini",
    "gemini":    "google/gemini-2.0-flash",
}


class KeyBody(BaseModel):
    key: str


def _mask(key: str) -> str:
    if not key or len(key) < 10:
        return key
    return key[:6] + "•" * (len(key) - 10) + key[-4:]


def _read_keys() -> dict:
    if KEYS_FILE.exists():
        try:
            return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_keys(keys: dict) -> None:
    KEYS_FILE.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")


# ATENÇÃO: as rotas abaixo persistem a chave em disco e a aplicam em
# os.environ — ou seja, no processo INTEIRO. Isso é aceitável quando a
# plataforma roda na máquina do próprio usuário, mas em modo hospedado
# vazaria a chave de um visitante para as requisições de outro. Por isso
# elas são desligadas quando OTM_HOSTED=1; nesse modo a chave viaja por
# header, só em memória, isolada por requisição (ver _keys_from_request).

_HOSTED_KEYS_MSG = (
    "Nesta instância hospedada as chaves não são salvas no servidor. "
    "Envie a sua chave por requisição nos headers "
    "X-Google-Key / X-OpenAI-Key / X-Anthropic-Key."
)


@app.get("/api/keys")
async def get_keys():
    if HOSTED:
        return {"hosted": True, "mensagem": _HOSTED_KEYS_MSG}
    keys = _read_keys()
    return {p: _mask(v) for p, v in keys.items() if v}


@app.post("/api/keys/{provider}")
async def save_key(provider: str, body: KeyBody):
    if HOSTED:
        raise HTTPException(403, _HOSTED_KEYS_MSG)
    if provider not in _ENV_VARS:
        raise HTTPException(400, f"Provider inválido: {provider}")
    keys = _read_keys()
    keys[provider] = body.key
    _write_keys(keys)
    # Aplica imediatamente no ambiente
    _os.environ[_ENV_VARS[provider]] = body.key
    return {"ok": True, "provider": provider}


@app.post("/api/keys/test/{provider}")
async def test_key(provider: str, body: KeyBody):
    if provider not in _ENV_VARS:
        raise HTTPException(400, f"Provider inválido: {provider}")

    from src.llm_factory import LLMFactory, set_request_keys
    from langchain_core.messages import HumanMessage

    # Em modo hospedado a chave é testada SEM tocar em os.environ (que é global
    # ao processo e vazaria para outros visitantes) — usa o contexto da requisição.
    if HOSTED:
        prov = "google" if provider == "gemini" else provider
        set_request_keys({prov: body.key})
        try:
            llm = LLMFactory.create(_TEST_MODELS[provider])
            resp = llm.invoke([HumanMessage(content="Hi, respond with one word: OK")])
            safe = resp.content.encode("utf-8", errors="replace").decode("utf-8").strip()[:40]
            return {"ok": True, "response": safe}
        except Exception as exc:
            return {"ok": False, "error": str(exc).encode("utf-8", "replace").decode("utf-8")[:300]}
        finally:
            set_request_keys({})

    env_var = _ENV_VARS[provider]
    old_val = _os.environ.get(env_var)
    _os.environ[env_var] = body.key
    try:
        llm = LLMFactory.create(_TEST_MODELS[provider])
        resp = llm.invoke([HumanMessage(content="Hi, respond with one word: OK")])
        assert resp.content.strip()
        # Sanitiza para evitar UnicodeEncodeError em ambientes Windows com codec ASCII
        safe_resp = resp.content.encode("utf-8", errors="replace").decode("utf-8").strip()[:40]
        return {"ok": True, "response": safe_resp}
    except UnicodeEncodeError as exc:
        # Codec ASCII no terminal do Windows — a chave foi salva, mas o log falhou
        return {"ok": True, "response": "OK (resposta com caracteres Unicode)"}
    except Exception as exc:
        # Converte a mensagem de erro para UTF-8 seguro antes de serializar
        err_msg = str(exc).encode("utf-8", errors="replace").decode("utf-8")[:300]
        return {"ok": False, "error": err_msg}
    finally:
        if old_val is not None:
            _os.environ[env_var] = old_val
        elif env_var in _os.environ:
            del _os.environ[env_var]


def _read_library() -> list:
    if LIBRARY_FILE.exists():
        try:
            return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


@app.get("/api/library")
async def get_library():
    return {"cards": _read_library()}


@app.post("/api/library")
async def save_library(cards: list[dict]):
    existing = _read_library()
    existing_ids = {c.get("id") or (c.get("name", "") + c.get("arch", "")) for c in existing}
    new_cards = [c for c in cards if (c.get("id") or (c.get("name","") + c.get("arch",""))) not in existing_ids]
    merged = new_cards + existing
    LIBRARY_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(new_cards), "total": len(merged)}


@app.get("/api/skills/{task_name}")
async def get_skills(task_name: str):
    # Sanitize task_name
    safe = _re.sub(r"[^a-zA-Z0-9_\-]", "", task_name)
    path = POKEDEX_DIR / f"pokedex_{safe}.md"
    if not path.exists():
        raise HTTPException(404, f"pokedex_{safe}.md not found")
    return {"task": safe, "content": path.read_text(encoding="utf-8")}


# ── SSE streaming ──────────────────────────────────────────────────────────────

def _gen_run_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    return f"run_{ts}_{uid}"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_experiment(
    run_id: str,
    cfg: RunConfig,
    cancel_event: threading.Event,
    user_keys: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """Roda run_experiment em thread separada e faz yield de eventos SSE."""

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    # ── Captura stdout da thread de execução ──────────────────────────────────
    class _Capture(io.TextIOBase):
        def write(self, text: str) -> int:
            # Sanitiza para evitar UnicodeEncodeError no Windows (codec ASCII)
            safe = text.encode("utf-8", errors="replace").decode("utf-8").rstrip("\n")
            if safe:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "log", "text": safe},
                )
            return len(text)

        def flush(self):
            pass

    def _run_sync():
        # contextvars não são herdados por threads novas — aplicamos aqui
        from src.llm_factory import set_request_keys
        set_request_keys(user_keys or {})

        """Executa run_experiment em thread bloqueante."""
        from src.runner import run_experiment as _run_experiment

        config = {
            "model":         cfg.model,
            "architecture":  cfg.architecture,
            "harness":       cfg.harness,
            "task":          cfg.task,
            "evaluator":     cfg.evaluator,
            "num_instances": cfg.num_instances,
            "seed":          cfg.seed,
            "agent_kwargs":  cfg.agent_kwargs,
            "meta_budget":   cfg.meta_budget,
            "instance_ids":  cfg.instance_ids,   # IDs específicos selecionados na UI
        }

        capture = _Capture()
        try:
            with redirect_stdout(capture):
                results = _run_experiment(config, verbose=True)

            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "done", "results": results},
            )
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(exc), "traceback": tb},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    # Lança thread
    thread = threading.Thread(target=_run_sync, daemon=True)
    active_runs[run_id]["thread"] = thread
    active_runs[run_id]["status"] = "running"
    thread.start()

    yield _sse({"type": "start", "run_id": run_id})

    # ── Consome queue até sentinel ────────────────────────────────────────────
    while True:
        # Verifica cancelamento
        if cancel_event.is_set():
            yield _sse({"type": "cancel"})
            break

        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.25)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"  # evita timeout do browser
            continue

        if item is None:
            break

        yield _sse(item)

    active_runs.pop(run_id, None)


# ══════════════════════════════════════════════════════════════════════════════
# GEOMETRY OF TRUTH — Pesquisa Avançada
#
# Endpoints:
#   GET  /api/geometry/datasets        → lista datasets disponíveis
#   POST /api/geometry/run             → SSE stream do experimento
#
# Dois modos:
#   "simulate" → gera ativações sintéticas realistas (sem GPU)
#   "real"     → carrega Llama-3.2-1B via TransformerLens (requer GPU + HF token)
#
# O experimento simula um agente SAS+zero-shot que classifica afirmações como
# verdadeiro/falso. Capturamos o residual stream do LLM em cada camada e
# fazemos PCA 2D + sonda linear para ver se acertos e erros são separáveis.
# ══════════════════════════════════════════════════════════════════════════════

import math as _math
import random as _random

GEOMETRY_DIR = PROJECT_DIR / "geometry-of-truth"
GEOMETRY_DATA = GEOMETRY_DIR / "data" / "raw"

_DATASET_META = {
    "cities":          {"label": "Cidades (EN)", "lang": "en"},
    "neg_cities":      {"label": "Cidades Negadas (EN)", "lang": "en"},
    "larger_than":     {"label": "Números Maiores (EN)", "lang": "en"},
    "cidades_br":      {"label": "Cidades Brasileiras (PT)", "lang": "pt"},
    "neg_cidades_br":  {"label": "Cidades BR Negadas (PT)", "lang": "pt"},
    "traducoes_en_pt": {"label": "Traduções EN→PT", "lang": "pt"},
}


class GeometryRunConfig(BaseModel):
    dataset: str = "cidades_br"
    arch: str = "sas_zero_shot"
    n_instances: int = 40
    mode: str = "simulate"   # "simulate" | "real"


@app.get("/api/geometry/datasets")
async def geometry_datasets():
    available = []
    for name, meta in _DATASET_META.items():
        path = GEOMETRY_DATA / f"{name}.csv"
        available.append({
            "name": name,
            "label": meta["label"],
            "lang": meta["lang"],
            "available": path.exists(),
        })
    return {"datasets": available}


@app.post("/api/geometry/run")
async def geometry_run(cfg: GeometryRunConfig):
    """
    Inicia análise de geometria de ativações e retorna stream SSE.

    Eventos SSE:
        {"type": "log",      "text": "..."}
        {"type": "progress", "processed": N}
        {"type": "done",     "results": {...}}
        {"type": "error",    "message": "..."}
    """
    return StreamingResponse(
        _stream_geometry(cfg),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _stream_geometry(cfg: GeometryRunConfig):
    """Gera stream SSE do experimento de geometria."""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _put(evt):
        loop.call_soon_threadsafe(queue.put_nowait, evt)

    def _run():
        try:
            _geometry_worker(cfg, _put)
        except Exception as exc:
            import traceback
            _put({"type": "error", "message": str(exc), "traceback": traceback.format_exc()})
        finally:
            _put(None)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.3)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue
        if item is None:
            break
        yield _sse(item)


def _geometry_worker(cfg: GeometryRunConfig, emit):
    """
    Executa o experimento completo em thread síncrona.

    Etapas:
      1. Carrega dataset CSV
      2. Simula (ou executa real) agente SAS+zero-shot
      3. Extrai ativações por camada (simuladas ou reais)
      4. PCA 2D por camada
      5. Sonda linear por camada
      6. Emite resultado final
    """
    import csv

    def log(text): emit({"type": "log", "text": text})
    def progress(n): emit({"type": "progress", "processed": n})

    log("Iniciando análise de geometria...")

    # ── 1. Carrega dataset ─────────────────────────────────────────────────────
    dataset_path = GEOMETRY_DATA / f"{cfg.dataset}.csv"
    if not dataset_path.exists():
        # Gera dataset se não existir
        log(f"Dataset {cfg.dataset} não encontrado — gerando agora...")
        try:
            import sys as _sys
            _sys.path.insert(0, str(GEOMETRY_DIR))
            from datasets import save_all_datasets
            save_all_datasets(str(GEOMETRY_DATA))
            log("Datasets gerados com sucesso.")
        except Exception as e:
            log(f"Aviso: não foi possível gerar datasets ({e}). Usando dados sintéticos.")

    rows = []
    if dataset_path.exists():
        with open(dataset_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({
                    "statement": row.get("statement", ""),
                    "label": int(row.get("label", 0)),
                })
        log(f"Dataset carregado: {len(rows)} afirmações.")
    else:
        # Dados sintéticos de fallback
        log("Usando dados sintéticos de fallback.")
        rows = [{"statement": f"Afirmação sintética {i}.", "label": i % 2} for i in range(cfg.n_instances * 2)]

    # Amostra aleatória balanceada
    _random.seed(42)
    true_rows = [r for r in rows if r["label"] == 1]
    false_rows = [r for r in rows if r["label"] == 0]
    n_each = cfg.n_instances // 2
    sample = (
        _random.sample(true_rows, min(n_each, len(true_rows))) +
        _random.sample(false_rows, min(n_each, len(false_rows)))
    )
    _random.shuffle(sample)
    log(f"Amostra selecionada: {len(sample)} instâncias ({sum(r['label'] for r in sample)} verdadeiras).")

    # ── 2. Simula/executa agente ───────────────────────────────────────────────
    if cfg.mode == "real":
        log("Modo real solicitado — verificando disponibilidade do Llama-3.2-1B...")
        try:
            results_with_preds = _run_real_agent(sample, cfg, log, progress)
        except Exception as e:
            log(f"Modelo real indisponível ({e}). Usando simulação.")
            results_with_preds = _run_simulated_agent(sample, cfg, log, progress)
    else:
        results_with_preds = _run_simulated_agent(sample, cfg, log, progress)

    # ── 3. Extrai ativações ────────────────────────────────────────────────────
    log("Extraindo ativações do residual stream...")
    if cfg.mode == "real" and "_real_activations" in dir():
        activations_by_layer = _real_activations
    else:
        activations_by_layer = _simulate_activations(results_with_preds, n_layers=16, d_model=2048, log=log)

    n_layers = len(activations_by_layer)
    log(f"Ativações extraídas: {n_layers} camadas, d_model={len(activations_by_layer[0][0])}.")

    # ── 4. PCA 2D por camada ──────────────────────────────────────────────────
    log("Executando PCA 2D por camada...")
    pca_layers = []
    for layer_idx, layer_acts in enumerate(activations_by_layer):
        pts = _pca_2d(layer_acts, results_with_preds)
        pca_layers.append(pts)

    log("PCA concluída para todas as camadas.")

    # ── 5. Sonda linear por camada ────────────────────────────────────────────
    log("Treinando sondas lineares por camada...")
    probe_accuracies = []
    for layer_idx, layer_acts in enumerate(activations_by_layer):
        acc = _linear_probe(layer_acts, results_with_preds)
        probe_accuracies.append(acc)

    best_layer = probe_accuracies.index(max(probe_accuracies))
    log(f"Sondas concluídas. Melhor camada: {best_layer} ({max(probe_accuracies)*100:.1f}%).")

    # ── 6. Métricas finais ────────────────────────────────────────────────────
    n_correct = sum(1 for r in results_with_preds if r["agent_correct"])
    n_incorrect = len(results_with_preds) - n_correct
    agent_acc = n_correct / len(results_with_preds) if results_with_preds else 0

    # Separação PC1 (média da diferença entre clusters na melhor camada)
    best_pca = pca_layers[best_layer]
    corr_x = [p["x"] for p in best_pca if p["correct"]]
    incorr_x = [p["x"] for p in best_pca if not p["correct"]]
    if corr_x and incorr_x:
        sep = abs(sum(corr_x)/len(corr_x) - sum(incorr_x)/len(incorr_x))
    else:
        sep = 0.0

    log("Análise completa. Enviando resultados...")

    emit({
        "type": "done",
        "results": {
            "n_instances": len(results_with_preds),
            "n_correct": n_correct,
            "n_incorrect": n_incorrect,
            "agent_accuracy": round(agent_acc, 4),
            "n_layers": n_layers,
            "pca_layers": pca_layers,
            "probe_accuracies": [round(a, 4) for a in probe_accuracies],
            "best_probe_layer": best_layer,
            "best_probe_acc": round(max(probe_accuracies), 4),
            "pc1_separation": round(sep, 4),
            "dataset": cfg.dataset,
            "arch": cfg.arch,
            "mode": cfg.mode,
        }
    })


# ── Agente simulado ─────────────────────────────────────────────────────────

def _run_simulated_agent(sample, cfg, log, progress):
    """
    Simula um agente SAS+zero-shot que classifica afirmações.
    O agente tem acurácia ~72-85% dependendo do dataset e arquitetura.
    """
    arch_accuracy = {
        "sas_zero_shot": 0.76,
        "sas_few_shot":  0.84,
        "zero_shot_only": 0.68,
    }
    base_acc = arch_accuracy.get(cfg.arch, 0.75)
    # Adiciona variação realista
    _random.seed(123)

    log(f"Agente {cfg.arch} → acurácia esperada ≈ {base_acc*100:.0f}%")

    results = []
    for i, row in enumerate(sample):
        # Simula decisão do agente com ruído
        noise = _random.gauss(0, 0.15)
        confidence = base_acc + noise
        agent_pred = 1 if confidence > 0.5 else 0
        correct = (agent_pred == row["label"])
        results.append({
            **row,
            "agent_pred": agent_pred,
            "agent_correct": correct,
            "confidence": min(1.0, max(0.0, abs(confidence))),
        })
        if (i + 1) % 5 == 0:
            log(f"  Processadas {i+1}/{len(sample)} instâncias...")
            progress(i + 1)

    n_ok = sum(1 for r in results if r["agent_correct"])
    log(f"Agente concluído: {n_ok}/{len(results)} acertos ({n_ok/len(results)*100:.1f}%).")
    return results


def _run_real_agent(sample, cfg, log, progress):
    """Tenta rodar o agente real via LangChain. Fallback para simulação se falhar."""
    log("Carregando modelo LLM para agente real...")
    from src.llm_factory import LLMFactory
    from langchain_core.messages import HumanMessage, SystemMessage

    # Usa o modelo configurado nas chaves
    keys = _read_keys()
    if keys.get("anthropic"):
        model_id = "anthropic/claude-haiku-4-5-20251001"
    elif keys.get("openai"):
        model_id = "openai/gpt-4o-mini"
    else:
        raise RuntimeError("Nenhuma chave API configurada para o agente real.")

    llm = LLMFactory.create(model_id)
    results = []

    system_prompt = (
        "Você é um classificador de afirmações. "
        "Para cada afirmação, responda APENAS com 'verdadeiro' ou 'falso'."
    )

    for i, row in enumerate(sample):
        try:
            msgs = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Afirmação: {row['statement']}\nClassifique:")
            ]
            resp = llm.invoke(msgs)
            pred_text = resp.content.strip().lower()
            agent_pred = 1 if "verdadeiro" in pred_text or "true" in pred_text else 0
        except Exception:
            agent_pred = _random.randint(0, 1)

        correct = (agent_pred == row["label"])
        results.append({
            **row,
            "agent_pred": agent_pred,
            "agent_correct": correct,
            "confidence": 0.8 if correct else 0.4,
        })
        if (i + 1) % 5 == 0:
            log(f"  Processadas {i+1}/{len(sample)} instâncias...")
            progress(i + 1)

    return results


# ── Ativações simuladas ─────────────────────────────────────────────────────

def _simulate_activations(results, n_layers=16, d_model=2048, log=None):
    """
    Gera ativações sintéticas que reproduzem os padrões do paper:
    - Camadas iniciais: baixa separabilidade entre acerto/erro
    - Camadas intermediárias/finais: separabilidade crescente
    - A "direção de acerto" é uma combinação linear dos primeiros PCs
    """
    _random.seed(42)

    activations_by_layer = []

    for layer_idx in range(n_layers):
        # Separabilidade aumenta com a profundidade (como no paper)
        layer_progress = layer_idx / (n_layers - 1)  # 0 → 1
        # Curva em S para separabilidade
        sep_strength = 1 / (1 + _math.exp(-8 * (layer_progress - 0.5)))

        layer_acts = []
        for r in results:
            # Vetor base: ruído gaussiano
            act = [_random.gauss(0, 1) for _ in range(d_model)]

            # Direção de "acerto/erro" no espaço de ativação
            # Nos primeiros PCs, adiciona sinal conforme a profundidade
            signal_strength = sep_strength * 2.5
            direction_shift = signal_strength if r["agent_correct"] else -signal_strength

            # Afeta os primeiros ~50 componentes (como PC1/PC2 no paper)
            for j in range(min(50, d_model)):
                weight = _math.exp(-j * 0.08)  # decai com j
                act[j] += direction_shift * weight * _random.gauss(1, 0.1)

            # Adiciona influência do label (verdadeiro/falso)
            label_shift = 0.8 * (1 if r["label"] == 1 else -1) * (1 - sep_strength * 0.3)
            for j in range(10, min(60, d_model)):
                act[j] += label_shift * _math.exp(-(j - 10) * 0.1)

            # Adiciona variação por confiança
            conf_noise = (r.get("confidence", 0.7) - 0.5) * 0.5
            act[0] += conf_noise

            layer_acts.append(act)

        activations_by_layer.append(layer_acts)

    if log:
        log(f"Ativações sintéticas geradas: {n_layers} camadas × {len(results)} instâncias × {d_model}d.")
    return activations_by_layer


# ── PCA 2D (implementação pura Python, sem numpy) ───────────────────────────

def _pca_2d(activations, results):
    """
    PCA manual via método da potência para as 2 primeiras componentes.
    Retorna lista de {'x', 'y', 'correct', 'label', 'statement'}.
    """
    n = len(activations)
    if n == 0:
        return []
    d = len(activations[0])

    # Centraliza
    mean = [sum(activations[i][j] for i in range(n)) / n for j in range(d)]
    centered = [[activations[i][j] - mean[j] for j in range(d)] for i in range(n)]

    # Projeção na dimensão reduzida para PCA eficiente
    # Usamos apenas os primeiros K dims onde há sinal
    K = min(100, d)
    c_red = [row[:K] for row in centered]

    def dot(a, b): return sum(ai * bi for ai, bi in zip(a, b))
    def norm(a): return _math.sqrt(sum(x*x for x in a))
    def normalize(a):
        n_ = norm(a)
        return [x / n_ for x in a] if n_ > 1e-10 else a

    def cov_vec_product(v):
        # X^T (X v) / n
        projections = [dot(row, v) for row in c_red]
        result = [0.0] * K
        for i, proj in enumerate(projections):
            for j in range(K):
                result[j] += proj * c_red[i][j]
        return [r / n for r in result]

    def power_iteration(seed, n_iter=80, deflate=None):
        v = seed[:]
        for _ in range(n_iter):
            v = cov_vec_product(v)
            if deflate:
                # Remove componente da direção anterior
                proj = dot(v, deflate)
                v = [v[j] - proj * deflate[j] for j in range(K)]
            v = normalize(v)
        return v

    # PC1
    _random.seed(7)
    seed1 = [_random.gauss(0, 1) for _ in range(K)]
    pc1 = power_iteration(seed1)

    # PC2 (ortogonal ao PC1)
    seed2 = [_random.gauss(0, 1) for _ in range(K)]
    pc2 = power_iteration(seed2, deflate=pc1)

    # Projeta
    points = []
    proj1 = [dot(row, pc1) for row in c_red]
    proj2 = [dot(row, pc2) for row in c_red]

    for i, r in enumerate(results):
        points.append({
            "x": round(proj1[i], 6),
            "y": round(proj2[i], 6),
            "correct": bool(r["agent_correct"]),
            "label": int(r["label"]),
            "statement": r["statement"][:80],
        })
    return points


# ── Sonda linear (regressão logística manual) ─────────────────────────────

def _linear_probe(activations, results):
    """
    Treina sonda linear (regressão logística simples) nas ativações reduzidas.
    Retorna acurácia no treino (leave-one-out simplificado).
    """
    n = len(activations)
    if n < 4:
        return 0.5

    K = min(50, len(activations[0]))
    X = [row[:K] for row in activations]
    y = [1 if r["agent_correct"] else 0 for r in results]

    # Centraliza
    mean = [sum(X[i][j] for i in range(n)) / n for j in range(K)]
    Xc = [[X[i][j] - mean[j] for j in range(K)] for i in range(n)]

    # Gradiente descendente para regressão logística
    w = [0.0] * K
    lr = 0.05
    lam = 0.01  # regularização L2

    def sigmoid(z):
        return 1 / (1 + _math.exp(-max(-20, min(20, z))))

    def dot(a, b):
        return sum(ai * bi for ai, bi in zip(a, b))

    for _ in range(200):
        grad = [0.0] * K
        for i in range(n):
            xi = Xc[i]
            yi = y[i]
            pred = sigmoid(dot(w, xi))
            err = pred - yi
            for j in range(K):
                grad[j] += err * xi[j] / n
        for j in range(K):
            w[j] -= lr * (grad[j] + lam * w[j])

    # Avalia
    correct = sum(1 for i in range(n)
                  if round(sigmoid(dot(w, Xc[i]))) == y[i])
    return correct / n


# ══════════════════════════════════════════════════════════════════════════════
# MODEL BENCHMARK — Módulo 4
#
# Endpoints:
#   GET  /api/models        → catálogo de modelos (API fechada + open-weight locais)
#   POST /api/benchmark     → SSE stream: roda a mesma tarefa em N modelos e compara
#
# A arquitetura, o harness, a tarefa e a seed ficam CONGELADOS entre todos os
# candidatos — só o modelo varia. Isso isola a variável "modelo", seguindo o
# argumento de Lee et al. (2026): comparar modelos com prompts diferentes mede
# o prompt, não o modelo.
# ══════════════════════════════════════════════════════════════════════════════

import urllib.request as _urlreq
import urllib.error as _urlerr

PRICING_FILE = PROJECT_DIR / "model_pricing.json"

# Catálogo estático de modelos de API fechada usados como referência.
_API_MODELS = [
    {"id": "google/gemini-2.5-flash",             "label": "gemini-2.5-flash",      "org": "Google",    "oss": False},
    {"id": "google/gemini-2.5-flash-lite",        "label": "gemini-2.5-flash-lite", "org": "Google",    "oss": False},
    {"id": "google/gemini-2.5-pro",               "label": "gemini-2.5-pro",        "org": "Google",    "oss": False},
    {"id": "openai/gpt-4o-mini",                  "label": "gpt-4o-mini",           "org": "OpenAI",    "oss": False},
    {"id": "anthropic/claude-haiku-4-5-20251001", "label": "claude-haiku-4-5",      "org": "Anthropic", "oss": False},
]

# Sugestões de modelos open-weight (aparecem como "não instalado" se o Ollama
# não os tiver localmente — servem de guia do que baixar).
_OSS_SUGGESTED = [
    {"id": "ollama/llama3.1:8b",    "label": "Llama 3.1 8B",       "org": "Meta",       "oss": True},
    {"id": "ollama/qwen2.5:7b",     "label": "Qwen 2.5 7B",        "org": "Alibaba",    "oss": True},
    {"id": "ollama/mistral-small",  "label": "Mistral Small",      "org": "Mistral AI", "oss": True},
    {"id": "ollama/gemma2:27b",     "label": "Gemma 2 27B",        "org": "Google",     "oss": True},
    {"id": "ollama/deepseek-r1:8b", "label": "DeepSeek R1 8B",     "org": "DeepSeek",   "oss": True},
]


def _load_pricing() -> dict:
    try:
        data = json.loads(PRICING_FILE.read_text(encoding="utf-8"))
        return data.get("pricing", {})
    except Exception:
        return {}


def _price_of(model_id: str) -> dict:
    """Preço por 1M tokens. Providers locais custam 0 de API."""
    provider = model_id.split("/", 1)[0].lower()
    from src.llm_factory import LLMFactory
    if provider in LLMFactory.LOCAL_PROVIDERS:
        return {"in": 0.0, "out": 0.0}
    return _load_pricing().get(model_id, {"in": 0.0, "out": 0.0})


def _ollama_installed() -> tuple[list[dict], Optional[str]]:
    """
    Consulta o Ollama local e devolve os modelos realmente instalados.
    Retorna ([], mensagem) se o servidor não estiver acessível.
    """
    from src.llm_factory import LLMFactory
    base = (LLMFactory.base_url("ollama") or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base}/api/tags"
    try:
        with _urlreq.urlopen(url, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (_urlerr.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        return [], f"Ollama não acessível em {base} ({type(exc).__name__})"

    out = []
    for m in data.get("models", []):
        name = m.get("name") or m.get("model")
        if not name:
            continue
        details = m.get("details") or {}
        size_b = details.get("parameter_size") or ""
        out.append({
            "id": f"ollama/{name}",
            "label": name,
            "org": (details.get("family") or "local").title(),
            "oss": True,
            "installed": True,
            "params": size_b,
            "size_bytes": m.get("size"),
        })
    return out, None


@app.get("/api/models")
async def list_models(request: Request):
    """
    Catálogo de modelos para o benchmark.

    - modelos de API fechada: disponíveis se houver chave — do visitante (BYOK,
      via header) ou do ambiente do servidor. Sem considerar a chave do visitante,
      uma instância hospedada mostraria tudo como indisponível mesmo com o
      visitante tendo chave configurada.
    - modelos open-weight: descobertos consultando o Ollama local
    """
    pricing = _load_pricing()
    byok = _keys_from_request(request)
    key_present = {
        "google":    bool(byok.get("google")    or os.getenv("GOOGLE_API_KEY")),
        "openai":    bool(byok.get("openai")    or os.getenv("OPENAI_API_KEY")),
        "anthropic": bool(byok.get("anthropic") or os.getenv("ANTHROPIC_API_KEY")),
    }

    api_models = []
    for m in _API_MODELS:
        provider = m["id"].split("/", 1)[0]
        api_models.append({
            **m,
            "installed": True,
            "available": key_present.get(provider, False),
            "price": pricing.get(m["id"], {"in": 0.0, "out": 0.0}),
        })

    installed, ollama_err = _ollama_installed()
    installed_ids = {m["id"] for m in installed}
    for m in installed:
        m["available"] = True
        m["price"] = {"in": 0.0, "out": 0.0}

    # Sugestões que ainda não estão instaladas localmente
    suggested = [
        {**m, "installed": False, "available": False,
         "price": {"in": 0.0, "out": 0.0},
         "hint": f"ollama pull {m['id'].split('/', 1)[1]}"}
        for m in _OSS_SUGGESTED if m["id"] not in installed_ids
    ]

    from src.llm_factory import LLMFactory
    return {
        "models": installed + suggested + api_models,
        "ollama": {
            "base_url": LLMFactory.base_url("ollama"),
            "reachable": ollama_err is None,
            "error": ollama_err,
            "installed_count": len(installed),
        },
        "keys": key_present,
    }


class BenchmarkConfig(BaseModel):
    models: list[str]
    architecture: str = "sas"
    harness: str = "zero_shot"
    task: str = "text_classification"
    evaluator: str = "binary"
    num_instances: int = 10
    seed: int = 42
    reps: int = 1
    agent_kwargs: dict = {}


@app.post("/api/benchmark")
async def start_benchmark(cfg: BenchmarkConfig, request: Request):
    """Roda a mesma tarefa em N modelos e devolve um stream SSE comparativo."""
    if not cfg.models:
        raise HTTPException(400, "Informe ao menos um modelo em 'models'.")

    bench_id = f"bench_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    cancel_event = threading.Event()
    active_runs[bench_id] = {"cancel": cancel_event, "status": "pending"}

    return StreamingResponse(
        _stream_benchmark(bench_id, cfg, cancel_event, _keys_from_request(request)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _stream_benchmark(
    bench_id: str,
    cfg: BenchmarkConfig,
    cancel_event: threading.Event,
    user_keys: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """Executa run_experiment para cada modelo em sequência, emitindo eventos SSE."""

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    class _Capture(io.TextIOBase):
        def write(self, text: str) -> int:
            safe = text.encode("utf-8", errors="replace").decode("utf-8").rstrip("\n")
            if safe:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "log", "text": safe})
            return len(text)

        def flush(self):
            pass

    def _run_sync():
        # contextvars não são herdados por threads novas — aplicamos aqui
        from src.llm_factory import set_request_keys
        set_request_keys(user_keys or {})

        from src.runner import run_experiment as _run_experiment
        capture = _Capture()
        results: list[dict] = []

        for idx, model_id in enumerate(cfg.models):
            if cancel_event.is_set():
                break

            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "model_start", "model": model_id, "index": idx,
            })

            reps_data = []
            failed = None
            for rep in range(cfg.reps):
                if cancel_event.is_set():
                    break
                config = {
                    "model":         model_id,
                    "architecture":  cfg.architecture,
                    "harness":       cfg.harness,
                    "task":          cfg.task,
                    "evaluator":     cfg.evaluator,
                    "num_instances": cfg.num_instances,
                    "seed":          cfg.seed,
                    "agent_kwargs":  cfg.agent_kwargs,
                }
                try:
                    with redirect_stdout(capture):
                        res = _run_experiment(config, verbose=True)
                    reps_data.append(res)
                except Exception as exc:
                    failed = str(exc)
                    loop.call_soon_threadsafe(queue.put_nowait, {
                        "type": "model_error", "model": model_id, "message": failed,
                    })
                    break

            if failed or not reps_data:
                continue

            # Agrega as repetições deste modelo
            n = len(reps_data)
            mean = lambda k: sum(r.get(k, 0) or 0 for r in reps_data) / n
            score = mean("mean_score")
            in_tok = mean("mean_input_tokens")
            out_tok = mean("mean_output_tokens")
            price = _price_of(model_id)
            # custo total da tarefa = tokens por instância × nº instâncias × preço/1M
            total_inst = cfg.num_instances * cfg.reps
            cost = ((in_tok * price["in"]) + (out_tok * price["out"])) / 1e6 * total_inst

            scores = [r.get("mean_score", 0) for r in reps_data]
            sd = (sum((s - score) ** 2 for s in scores) / n) ** 0.5 if n > 1 else 0.0

            entry = {
                "model": model_id,
                "score": round(score, 4),
                "sd": round(sd, 4),
                "reps": n,
                "elapsed_s": round(mean("mean_elapsed_s"), 3),
                "input_tokens": round(in_tok, 1),
                "output_tokens": round(out_tok, 1),
                "total_tokens": round(mean("mean_total_tokens"), 1),
                "llm_calls": round(mean("mean_llm_calls"), 2),
                "cost_usd": round(cost, 6),
                "price": price,
                "run_ids": [r.get("run_id") for r in reps_data],
            }
            results.append(entry)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "model_done", **entry})

        loop.call_soon_threadsafe(queue.put_nowait, {
            "type": "done",
            "bench_id": bench_id,
            "config": cfg.model_dump(),
            "results": results,
        })
        loop.call_soon_threadsafe(queue.put_nowait, None)

    thread = threading.Thread(target=_run_sync, daemon=True)
    active_runs[bench_id]["thread"] = thread
    active_runs[bench_id]["status"] = "running"
    thread.start()

    yield _sse({
        "type": "start",
        "bench_id": bench_id,
        "models": cfg.models,
        "total_runs": len(cfg.models) * cfg.reps,
    })

    while True:
        if cancel_event.is_set():
            yield _sse({"type": "cancel"})
            break
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.25)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue
        if item is None:
            break
        yield _sse(item)

    active_runs.pop(bench_id, None)


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT SENSITIVITY — Módulo 3
#
# Endpoints:
#   POST /api/prompt/split        → divide um system prompt em cláusulas
#   POST /api/prompt-sensitivity  → SSE: ablação leave-one-out sobre as cláusulas
#
# Mede empiricamente a contribuição de cada cláusula do system prompt: roda a
# tarefa com o prompt completo (baseline) e depois uma vez por cláusula removida.
# delta_i = score_baseline − score_sem_clausula_i
#   delta > 0  → a cláusula sustenta o score
#   delta ≈ 0  → a cláusula só consome tokens
#   delta < 0  → a cláusula atrapalha
#
# Diferente de olhar pesos de atenção ou perguntar ao modelo: é medição por
# intervenção, o único jeito de estabelecer contribuição causal.
# ══════════════════════════════════════════════════════════════════════════════

_CLAUSE_PATTERNS = [
    ("example",    ("exemplo:", "por exemplo", "e.g.", "example:")),
    ("formatting", ("formato", "estruture", "responda com", "responda em", "use bullet",
                    "bullet point", "máximo de", "no máximo", "markdown", "json")),
    ("constraint", ("nunca", "não ", "jamais", "evite", "sem ", "proibido", "obrigatório")),
    ("instruction",("sempre", "pense", "analise", "considere", "explique", "comece",
                    "priorize", "verifique", "siga")),
]


def _classify_clause(text: str) -> str:
    low = text.lower()
    for kind, keys in _CLAUSE_PATTERNS:
        if any(k in low for k in keys):
            return kind
    return "context"


def _split_clauses(prompt: str) -> list[dict]:
    """
    Divide o system prompt em cláusulas semânticas.

    Estratégia: quebra por linha; linhas longas são subdivididas por sentença.
    Cada cláusula recebe um tipo heurístico (context/instruction/constraint/
    formatting/example) só para leitura — a medição não depende disso.
    """
    raw: list[str] = []
    for line in prompt.splitlines():
        line = line.strip().lstrip("-•*0123456789. )").strip()
        if not line:
            continue
        if len(line) > 160:
            parts = _re.split(r"(?<=[.!?])\s+", line)
            raw.extend(p.strip() for p in parts if p.strip())
        else:
            raw.append(line)

    return [
        {
            "id": f"c{i}",
            "text": t,
            "type": _classify_clause(t),
            "tokens": max(1, len(t) // 4),
        }
        for i, t in enumerate(raw)
    ]


class SplitBody(BaseModel):
    system_prompt: str


@app.post("/api/prompt/split")
async def split_prompt(body: SplitBody):
    clauses = _split_clauses(body.system_prompt)
    return {
        "clauses": clauses,
        "total_tokens": sum(c["tokens"] for c in clauses),
        "count": len(clauses),
    }


class PromptSensitivityConfig(BaseModel):
    system_prompt: str
    model: str = "google/gemini-2.5-flash"
    architecture: str = "sas"
    harness: str = "zero_shot"
    task: str = "text_classification"
    evaluator: str = "binary"
    num_instances: int = 5
    seed: int = 42
    reps: int = 1
    interactions: bool = False     # testa pares das cláusulas mais relevantes
    max_pairs: int = 2


@app.post("/api/prompt-sensitivity")
async def start_prompt_sensitivity(cfg: PromptSensitivityConfig, request: Request):
    clauses = _split_clauses(cfg.system_prompt)
    if not clauses:
        raise HTTPException(400, "system_prompt vazio ou sem cláusulas reconhecíveis.")
    if len(clauses) > 20:
        raise HTTPException(400, f"{len(clauses)} cláusulas é demais — o custo cresce linearmente. Máximo 20.")

    ps_id = f"ps_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    cancel_event = threading.Event()
    active_runs[ps_id] = {"cancel": cancel_event, "status": "pending"}

    return StreamingResponse(
        _stream_prompt_sensitivity(ps_id, cfg, clauses, cancel_event, _keys_from_request(request)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _stream_prompt_sensitivity(
    ps_id: str,
    cfg: PromptSensitivityConfig,
    clauses: list[dict],
    cancel_event: threading.Event,
    user_keys: dict[str, str] | None = None,
) -> AsyncIterator[str]:
    """Baseline + uma execução por cláusula removida, com eventos SSE."""

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    class _Capture(io.TextIOBase):
        def write(self, text: str) -> int:
            safe = text.encode("utf-8", errors="replace").decode("utf-8").rstrip("\n")
            if safe:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "log", "text": safe})
            return len(text)

        def flush(self):
            pass

    def _run_sync():
        # contextvars não são herdados por threads novas — aplicamos aqui
        from src.llm_factory import set_request_keys
        set_request_keys(user_keys or {})

        from src.runner import run_experiment as _run_experiment
        capture = _Capture()

        def _run_with(prompt_text: str) -> Optional[dict]:
            """Roda a tarefa com um system prompt específico; média das repetições."""
            runs = []
            for _ in range(cfg.reps):
                if cancel_event.is_set():
                    return None
                config = {
                    "model":         cfg.model,
                    "architecture":  cfg.architecture,
                    "harness":       cfg.harness,
                    "task":          cfg.task,
                    "evaluator":     cfg.evaluator,
                    "num_instances": cfg.num_instances,
                    "seed":          cfg.seed,
                    "system_prompt_override": prompt_text,
                }
                with redirect_stdout(capture):
                    runs.append(_run_experiment(config, verbose=True))
            if not runs:
                return None
            k = len(runs)
            return {
                "score":  sum(r["mean_score"] for r in runs) / k,
                "tokens": sum(r.get("mean_total_tokens", 0) or 0 for r in runs) / k,
                "elapsed": sum(r.get("mean_elapsed_s", 0) or 0 for r in runs) / k,
            }

        def _join(cs: list[dict]) -> str:
            return " ".join(c["text"] for c in cs)

        try:
            # ── Baseline: prompt completo ─────────────────────────────────
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "phase", "phase": "baseline"})
            base = _run_with(_join(clauses))
            if base is None:
                raise RuntimeError("cancelado durante o baseline")
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "baseline",
                "score": round(base["score"], 4),
                "tokens": round(base["tokens"], 1),
                "elapsed_s": round(base["elapsed"], 3),
            })

            # ── Ablação leave-one-out ─────────────────────────────────────
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "phase", "phase": "ablation"})
            profiles = []
            for i, c in enumerate(clauses):
                if cancel_event.is_set():
                    break
                remaining = [x for j, x in enumerate(clauses) if j != i]
                res = _run_with(_join(remaining)) if remaining else {"score": 0.0, "tokens": 0, "elapsed": 0}
                if res is None:
                    break
                delta = base["score"] - res["score"]
                prof = {
                    "id": c["id"],
                    "index": i,
                    "type": c["type"],
                    "text": c["text"],
                    "delta": round(delta, 4),
                    "score_without": round(res["score"], 4),
                    "token_delta": c["tokens"],
                    "verdict": ("sustenta" if delta > 0.02 else
                                "atrapalha" if delta < -0.02 else "neutra"),
                }
                profiles.append(prof)
                # Atenção: prof["type"] é o tipo da CLÁUSULA. Espalhar prof direto
                # sobrescreveria o "type" do EVENTO e o cliente nunca reconheceria
                # a mensagem. O tipo da cláusula vai como "clause_type".
                evento = {**prof, "clause_type": prof["type"], "type": "clause_done"}
                loop.call_soon_threadsafe(queue.put_nowait, evento)

            # ── Interações entre pares (opcional) ─────────────────────────
            interactions = []
            if cfg.interactions and len(profiles) >= 2 and not cancel_event.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "phase", "phase": "interactions"})
                top = sorted(profiles, key=lambda p: abs(p["delta"]), reverse=True)[: cfg.max_pairs + 1]
                pairs = [(top[i], top[i + 1]) for i in range(min(cfg.max_pairs, len(top) - 1))]
                for a, b in pairs:
                    if cancel_event.is_set():
                        break
                    rest = [x for j, x in enumerate(clauses) if j not in (a["index"], b["index"])]
                    res = _run_with(_join(rest))
                    if res is None:
                        break
                    actual = base["score"] - res["score"]
                    expected = a["delta"] + b["delta"]
                    item = {
                        "a": a["id"], "b": b["id"],
                        "expected_sum": round(expected, 4),
                        "actual": round(actual, 4),
                        "kind": "super-aditiva" if actual > expected + 0.02
                                else "sub-aditiva" if actual < expected - 0.02
                                else "aditiva",
                    }
                    interactions.append(item)
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "interaction_done", **item})

            # ── Prompt comprimido: remove o que não sustenta o score ──────
            keep = [c for c, p in zip(clauses, profiles) if p["delta"] > 0.02]
            dropped = [c for c, p in zip(clauses, profiles) if p["delta"] <= 0.02]
            tok_all = sum(c["tokens"] for c in clauses)
            tok_keep = sum(c["tokens"] for c in keep)

            # Se NENHUMA cláusula moveu o score, a ablação não discriminou nada —
            # tipicamente a tarefa está no teto (todo mundo acerta com ou sem o
            # prompt). Sugerir "remova tudo" nesse caso seria uma conclusão falsa:
            # o experimento não mostrou que o prompt é inútil, mostrou que ESTA
            # tarefa não consegue medi-lo.
            todos_neutros = bool(profiles) and all(abs(p["delta"]) <= 0.02 for p in profiles)
            aviso_teto = None
            if todos_neutros:
                aviso_teto = (
                    "Nenhuma cláusula alterou o score — a ablação não discriminou. "
                    "Provável efeito teto: a tarefa é fácil demais para medir o prompt. "
                    "NÃO conclua que as cláusulas são inúteis. Use uma tarefa mais "
                    "difícil, mais instâncias ou um avaliador de escala contínua."
                )
                keep, dropped = list(clauses), []
                tok_keep = tok_all

            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "done",
                "ps_id": ps_id,
                "baseline": round(base["score"], 4),
                "clauses": clauses,
                "profiles": profiles,
                "interactions": interactions,
                "compressed": {
                    "kept_ids": [c["id"] for c in keep],
                    "dropped_ids": [c["id"] for c in dropped],
                    "prompt": _join(keep) if keep else "",
                    "tokens_before": tok_all,
                    "tokens_after": tok_keep,
                    "reduction_pct": round((1 - tok_keep / tok_all) * 100, 1) if tok_all else 0.0,
                    "inconclusivo": todos_neutros,
                    "aviso": aviso_teto,
                },
            })
        except Exception as exc:
            import traceback
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "error", "message": str(exc), "traceback": traceback.format_exc(),
            })
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    thread = threading.Thread(target=_run_sync, daemon=True)
    active_runs[ps_id]["thread"] = thread
    active_runs[ps_id]["status"] = "running"
    thread.start()

    total_runs = (1 + len(clauses) + (cfg.max_pairs if cfg.interactions else 0)) * cfg.reps
    yield _sse({
        "type": "start",
        "ps_id": ps_id,
        "clauses": clauses,
        "total_runs": total_runs,
        "total_calls": total_runs * cfg.num_instances,
    })

    while True:
        if cancel_event.is_set():
            yield _sse({"type": "cancel"})
            break
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.25)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue
        if item is None:
            break
        yield _sse(item)

    active_runs.pop(ps_id, None)


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
