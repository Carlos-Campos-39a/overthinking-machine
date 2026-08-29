"""
validate_platform.py — Verificação de integridade da Overthinking Machine.

Roda uma bateria de checagens em todas as camadas da plataforma e devolve um
relatório com veredito por camada. Feito para ser reexecutado a cada mudança:
é a rede de segurança que permite mexer no pipeline sem quebrar silenciosamente
um experimento que só falharia 300 chamadas depois.

USO
    python validate_platform.py              # camadas offline (sem custo)
    python validate_platform.py --api        # inclui a API (precisa do uvicorn no ar)
    python validate_platform.py --mcp        # inclui handshake MCP
    python validate_platform.py --live       # inclui 1 chamada real de LLM (tem custo)
    python validate_platform.py --all        # tudo

Códigos de saída: 0 = tudo passou, 1 = alguma checagem falhou.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Console do Windows usa cp1252 por padrão e quebra em qualquer acento.
# Mesma correção aplicada em server.py — precisa vir antes do primeiro print.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJ = Path(__file__).parent
sys.path.insert(0, str(PROJ))

API_URL = os.getenv("OTM_API_URL", "http://localhost:8000").rstrip("/")

OK, FAIL, WARN, SKIP = "OK", "FALHA", "AVISO", "PULADO"
_resultados: list[tuple[str, str, str, str]] = []   # (camada, checagem, status, detalhe)


def check(camada: str, nome: str, status: str, detalhe: str = "") -> None:
    _resultados.append((camada, nome, status, detalhe))
    icone = {OK: "[ok]", FAIL: "[XX]", WARN: "[!!]", SKIP: "[--]"}[status]
    linha = f"  {icone} {nome}"
    if detalhe:
        linha += f" — {detalhe}"
    print(linha, flush=True)


def secao(titulo: str) -> None:
    print(f"\n{titulo}\n" + "─" * 66, flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Ambiente
# ══════════════════════════════════════════════════════════════════════════════

def val_ambiente() -> None:
    secao("1. AMBIENTE")

    v = sys.version_info
    check("ambiente", "Python >= 3.10", OK if v >= (3, 10) else FAIL,
          f"{v.major}.{v.minor}.{v.micro}")

    pacotes = ["langchain_core", "langchain_google_genai", "fastapi", "uvicorn",
               "typer", "rich", "yaml", "pydantic", "dotenv", "httpx", "mcp"]
    faltando = []
    for p in pacotes:
        try:
            __import__(p)
        except ImportError:
            faltando.append(p)
    check("ambiente", f"dependências ({len(pacotes)})",
          OK if not faltando else FAIL,
          "todas presentes" if not faltando else f"faltando: {', '.join(faltando)}")

    env = PROJ / ".env"
    if not env.exists():
        check("ambiente", ".env", FAIL, "arquivo não existe")
    else:
        from dotenv import load_dotenv
        load_dotenv(env)
        chaves = {k: bool(os.getenv(k)) for k in
                  ("GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")}
        presentes = [k for k, v in chaves.items() if v]
        # chaves curtas demais quase sempre são placeholder
        suspeitas = [k for k in presentes if len(os.getenv(k, "")) < 20]
        if not presentes:
            check("ambiente", "chaves de API", FAIL, "nenhuma configurada")
        elif suspeitas:
            check("ambiente", "chaves de API", WARN,
                  f"{len(presentes)} presente(s); suspeitas de placeholder: {', '.join(suspeitas)}")
        else:
            check("ambiente", "chaves de API", OK, f"{len(presentes)} configurada(s)")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Código
# ══════════════════════════════════════════════════════════════════════════════

def val_codigo() -> None:
    secao("2. CÓDIGO")

    alvos = ["run.py", "server.py", "mcp_server.py", "validate_platform.py"]
    alvos += [str(p.relative_to(PROJ)) for p in (PROJ / "src").rglob("*.py")
              if "__pycache__" not in str(p)]

    falhas = []
    for a in alvos:
        r = subprocess.run([sys.executable, "-m", "py_compile", str(PROJ / a)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            falhas.append(f"{a}: {r.stderr.strip().splitlines()[-1][:70]}")
    check("codigo", f"compilação ({len(alvos)} arquivos)",
          OK if not falhas else FAIL,
          "sem erros de sintaxe" if not falhas else "; ".join(falhas[:3]))

    # Caracteres que quebram o console do Windows (cp1252) em código executável
    ruins = []
    for a in alvos:
        for i, linha in enumerate((PROJ / a).read_text(encoding="utf-8").splitlines(), 1):
            s = linha.strip()
            if s.startswith("#") or not any(ch in linha for ch in "→✓✗•★"):
                continue
            if "print(" in linha or "f\"" in linha and "=" in linha:
                if any(ch in linha for ch in "→✓✗"):
                    ruins.append(f"{a}:{i}")
    check("codigo", "unicode em saída de console",
          OK if not ruins else WARN,
          "nenhum caractere problemático" if not ruins
          else f"verificar: {', '.join(ruins[:3])}")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Registros do pipeline
# ══════════════════════════════════════════════════════════════════════════════

def val_registros() -> None:
    secao("3. REGISTROS DO PIPELINE")

    from src.task_base import TaskRegistry
    from src.agents.agent_factory import list_architectures
    from src.harnesses.manual_harnesses import HARNESSES
    from src.llm_factory import LLMFactory

    arqs = list_architectures()
    esperado_arq = {"sas", "independent", "centralized", "decentralized", "hybrid"}
    check("registros", "5 arquiteturas", OK if set(arqs) == esperado_arq else FAIL,
          ", ".join(arqs))

    harn = set(HARNESSES) | {"meta_harness"}
    esperado_h = {"zero_shot", "few_shot", "ace", "mce", "meta_harness"}
    check("registros", "5 harnesses", OK if harn == esperado_h else FAIL,
          ", ".join(sorted(harn)))

    tasks = TaskRegistry.list_available()
    check("registros", "tarefas registradas",
          OK if len(tasks) >= 2 else FAIL, ", ".join(tasks))

    from src.evaluators.evaluators import get_evaluator
    try:
        get_evaluator("binary")
        check("registros", "avaliador binary", OK)
    except Exception as e:
        check("registros", "avaliador binary", FAIL, str(e)[:60])

    # Providers do LLMFactory, incluindo os locais de peso aberto
    try:
        p_local = list(LLMFactory.LOCAL_PROVIDERS)
        prov = list(LLMFactory.PROVIDERS)
        check("registros", "providers de LLM", OK,
              f"{len(prov)} ({', '.join(prov)}); locais: {', '.join(p_local)}")
    except Exception as e:
        check("registros", "providers de LLM", FAIL, str(e)[:60])


# ══════════════════════════════════════════════════════════════════════════════
# 4. Comportamentos críticos (sem gastar LLM)
# ══════════════════════════════════════════════════════════════════════════════

def val_comportamentos() -> None:
    secao("4. COMPORTAMENTOS CRÍTICOS (sem custo)")

    from src.task_base import TaskRegistry
    from src.harnesses.manual_harnesses import get_harness, _system
    from src.llm_factory import LLMFactory

    task = TaskRegistry.get("text_classification", num_instances=2, seed=42)
    inst = task.sample()[0]

    # (a) vocabulário de rótulos precisa chegar ao prompt — sem isso o modelo
    #     responde certo mas fora do vocabulário e conta como erro
    msgs = get_harness("zero_shot").build_messages(inst).messages
    tem = "valid_labels" in inst.metadata and any(
        r.lower() in msgs[1].content.lower() for r in inst.metadata["valid_labels"][:2])
    check("comportamento", "valid_labels injetados no prompt",
          OK if tem else FAIL, "modelo recebe o vocabulário fechado")

    # (b) override de system prompt (base do módulo 3)
    padrao = _system(inst)
    inst.metadata = {**inst.metadata, "system_override": "PROMPT_DE_TESTE"}
    trocado = _system(inst)
    inst.metadata.pop("system_override")
    check("comportamento", "override de system prompt",
          OK if trocado == "PROMPT_DE_TESTE" and padrao != trocado else FAIL,
          "ablação de prompt consegue variar o prompt")

    # (c) reprodutibilidade da amostragem por seed
    a = [i.id for i in TaskRegistry.get("text_classification", num_instances=5, seed=42).sample()]
    b = [i.id for i in TaskRegistry.get("text_classification", num_instances=5, seed=42).sample()]
    c = [i.id for i in TaskRegistry.get("text_classification", num_instances=5, seed=7).sample()]
    check("comportamento", "seed reproduz a amostra",
          OK if a == b and a != c else FAIL,
          "mesma seed = mesmas instâncias; seed diferente = amostra diferente")

    # (d) providers locais não podem exigir chave de API
    try:
        LLMFactory._check_api_key("ollama")
        llm = LLMFactory.create("ollama/llama3.1:8b")
        base = str(getattr(llm, "openai_api_base", ""))
        check("comportamento", "provider open-weight sem chave",
              OK if "11434" in base else FAIL, f"base_url={base}")
    except Exception as e:
        check("comportamento", "provider open-weight sem chave", FAIL, str(e)[:70])

    # (e) tabela de preços
    try:
        pricing = json.loads((PROJ / "model_pricing.json").read_text(encoding="utf-8"))
        n = len(pricing.get("pricing", {}))
        check("comportamento", "tabela de preços", OK if n >= 5 else WARN,
              f"{n} modelos precificados")
    except Exception as e:
        check("comportamento", "tabela de preços", FAIL, str(e)[:60])


# ══════════════════════════════════════════════════════════════════════════════
# 5. Boilerplate
# ══════════════════════════════════════════════════════════════════════════════

def val_boilerplate() -> None:
    secao("5. BOILERPLATE")

    tmpl = PROJ / "boilerplate" / "minha_tarefa.py"
    readme = PROJ / "boilerplate" / "README.md"
    check("boilerplate", "arquivos presentes",
          OK if tmpl.exists() and readme.exists() else FAIL,
          "minha_tarefa.py + README.md")
    if not tmpl.exists():
        return

    destino = PROJ / "src" / "tasks" / "_val_tmp_task.py"
    try:
        destino.write_text(tmpl.read_text(encoding="utf-8"), encoding="utf-8")
        r = subprocess.run([sys.executable, "run.py", "--list-tasks"],
                           capture_output=True, text=True, cwd=str(PROJ),
                           encoding="utf-8", errors="replace")
        achou = "minha_tarefa" in (r.stdout or "")
        check("boilerplate", "tarefa template é auto-descoberta",
              OK if achou else FAIL,
              "aparece em --list-tasks ao ser copiada para src/tasks/")

        if achou:
            code = (
                "import sys; sys.path.insert(0, r'%s')\n"
                "from src.task_base import TaskRegistry\n"
                "t = TaskRegistry.get('minha_tarefa', num_instances=3, seed=42)\n"
                "i = [x for x in t.sample() if x.ground_truth=='reprovado'][0]\n"
                "print(t.score('reprovado', i), t.score('Resposta: reprovado', i), "
                "t.score('aprovado', i), t.score('sem rotulo', i))\n" % str(PROJ)
            )
            r2 = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                text=True, cwd=str(PROJ), encoding="utf-8", errors="replace")
            vals = (r2.stdout or "").strip().split()
            esperado = ["1.0", "1.0", "0.0", "0.0"]
            check("boilerplate", "score() do template",
                  OK if vals == esperado else FAIL,
                  f"exato/prefixo/errado/sem-rótulo = {' '.join(vals) or r2.stderr[:50]}")
    finally:
        destino.unlink(missing_ok=True)
        for p in (PROJ / "src" / "tasks" / "__pycache__").glob("_val_tmp_task*"):
            p.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Frontend
# ══════════════════════════════════════════════════════════════════════════════

def val_frontend() -> None:
    secao("6. FRONTEND")

    paginas = {
        "overthinking-machine.html": "Módulo 1 · laboratório",
        "pesquisa-avancada.html": "Módulo 2 · rede neural",
        "prompt-sensitivity-benchmark.html": "Módulo 3 · prompt",
        "model-benchmark.html": "Módulo 4 · modelos",
    }
    for arq, desc in paginas.items():
        p = PROJ / arq
        if not p.exists():
            check("frontend", desc, FAIL, "arquivo não existe")
            continue
        html = p.read_text(encoding="utf-8", errors="replace")
        problemas = []
        if html.count("<script") != html.count("</script>"):
            problemas.append("tags <script> desbalanceadas")
        if "<title>" not in html:
            problemas.append("sem <title>")
        check("frontend", desc, OK if not problemas else FAIL,
              f"{len(html)//1024} KB" if not problemas else "; ".join(problemas))

    # Long Doc deve estar oculto da navegação, mas o arquivo preservado
    idx = (PROJ / "overthinking-machine.html").read_text(encoding="utf-8", errors="replace")
    check("frontend", "Long Doc oculto da navegação",
          OK if "long-doc" not in idx else FAIL,
          "arquivo preservado no disco" if (PROJ / "long-doc-benchmark.html").exists()
          else "arquivo removido do disco")

    # Os 4 módulos linkados a partir da home
    links = ["#testes", "pesquisa-avancada.html",
             "prompt-sensitivity-benchmark.html", "model-benchmark.html"]
    faltando = [l for l in links if l not in idx]
    check("frontend", "4 módulos linkados na home",
          OK if not faltando else FAIL,
          "todos" if not faltando else f"faltando: {faltando}")


# ══════════════════════════════════════════════════════════════════════════════
# 7. API
# ══════════════════════════════════════════════════════════════════════════════

def _http_json(path: str, body: dict | None = None, timeout: int = 20):
    url = f"{API_URL}{path}"
    if body is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def val_api() -> None:
    secao("7. API (FastAPI)")

    try:
        h = _http_json("/api/health", timeout=5)
        check("api", "/api/health", OK if h.get("status") == "ok" else FAIL, API_URL)
    except Exception as e:
        check("api", "/api/health", FAIL,
              f"API offline em {API_URL} — suba com: python -m uvicorn server:app --port 8000")
        for nome in ("/api/models", "/api/prompt/split", "rotas registradas"):
            check("api", nome, SKIP, "API offline")
        return

    try:
        m = _http_json("/api/models")
        disp = [x for x in m["models"] if x.get("available")]
        check("api", "/api/models", OK,
              f"{len(m['models'])} modelos, {len(disp)} disponíveis; "
              f"ollama={'on' if m['ollama']['reachable'] else 'off'}")
    except Exception as e:
        check("api", "/api/models", FAIL, str(e)[:70])

    try:
        s = _http_json("/api/prompt/split",
                       {"system_prompt": "Você é um classificador.\nResponda com uma palavra."})
        check("api", "/api/prompt/split", OK if s["count"] == 2 else FAIL,
              f"{s['count']} cláusulas, {s['total_tokens']} tokens")
    except Exception as e:
        check("api", "/api/prompt/split", FAIL, str(e)[:70])

    # Rotas esperadas presentes no app
    try:
        import server as S
        rotas = {r.path for r in S.app.routes if hasattr(r, "path")}
        precisa = {"/api/health", "/api/run", "/api/models", "/api/benchmark",
                   "/api/prompt/split", "/api/prompt-sensitivity",
                   "/api/geometry/run", "/api/keys"}
        falta = precisa - rotas
        check("api", "rotas registradas", OK if not falta else FAIL,
              f"{len(precisa)} rotas-chave presentes" if not falta else f"faltando {falta}")
    except Exception as e:
        check("api", "rotas registradas", FAIL, str(e)[:70])


# ══════════════════════════════════════════════════════════════════════════════
# 8. MCP
# ══════════════════════════════════════════════════════════════════════════════

def val_mcp() -> None:
    secao("8. MCP")

    try:
        import mcp_server as M
    except Exception as e:
        check("mcp", "importar mcp_server", FAIL, str(e)[:70])
        return

    async def _inspect():
        tools = await M.server.list_tools()
        prompts = await M.server.list_prompts()
        res = await M.server.list_resources()
        return tools, prompts, res

    try:
        tools, prompts, res = asyncio.run(_inspect())
    except Exception as e:
        check("mcp", "listar capacidades MCP", FAIL, str(e)[:70])
        return

    esperadas = {"listar_capacidades", "estimar_custo", "validar_pipeline",
                 "rodar_experimento", "comparar_modelos", "analisar_prompt",
                 "dividir_prompt"}
    nomes = {t.name for t in tools}
    check("mcp", "7 ferramentas", OK if esperadas <= nomes else FAIL,
          ", ".join(sorted(nomes)))

    pesperados = {"protocolo_validacao", "escolher_arquitetura",
                  "escolher_modelo", "otimizar_prompt"}
    pnomes = {p.name for p in prompts}
    check("mcp", "4 prompts guiados", OK if pesperados <= pnomes else FAIL,
          ", ".join(sorted(pnomes)))

    uris = {str(r.uri) for r in res}
    check("mcp", "recursos de metodologia",
          OK if {"otm://metodologia", "otm://referencias"} <= uris else FAIL,
          ", ".join(sorted(uris)))

    # A metodologia precisa cobrir os princípios — é o que diferencia a plataforma
    metodologia = M.METODOLOGIA
    principios = ["Isolar uma variável", "Validar barato", "Justificar o n",
                  "Score sozinho não é resultado", "efeito teto"]
    faltando = [p for p in principios if p.lower() not in metodologia.lower()]
    check("mcp", "metodologia cobre os 5 princípios",
          OK if not faltando else FAIL,
          f"{len(metodologia)} chars" if not faltando else f"faltando: {faltando}")

    # Ferramenta sem custo, executada de verdade
    async def _custo(**kw):
        r = await M.server.call_tool("estimar_custo", kw)
        txt = r.content[0].text if getattr(r, "content", None) else str(r)
        return json.loads(txt) if txt.strip().startswith("{") else {}

    try:
        # (a) aritmética: 3 modelos × 10 inst × 2 reps × 8 chamadas (hybrid) = 480
        d = asyncio.run(_custo(n_modelos=3, arquitetura="hybrid",
                               num_instancias=10, reps=2))
        ok_calc = d.get("total_chamadas_llm") == 480
        check("mcp", "estimar_custo: aritmética", OK if ok_calc else FAIL,
              f"{d.get('total_chamadas_llm')} chamadas (esperado 480)")

        # (b) escalonamento de risco: experimento pequeno não avisa, grande avisa
        pequeno = asyncio.run(_custo(n_modelos=1, arquitetura="sas",
                                     num_instancias=10, reps=1))          # 10
        grande = asyncio.run(_custo(n_modelos=5, arquitetura="hybrid",
                                    num_instancias=20, reps=2))           # 1600
        ok_risco = (pequeno.get("aviso") is None
                    and pequeno.get("nivel_risco") == "desprezivel"
                    and grande.get("nivel_risco") == "alto"
                    and bool(grande.get("aviso")))
        check("mcp", "estimar_custo: alerta de risco", OK if ok_risco else FAIL,
              f"10 chamadas={pequeno.get('nivel_risco')}, "
              f"{grande.get('total_chamadas_llm')} chamadas={grande.get('nivel_risco')}")
    except Exception as e:
        check("mcp", "estimar_custo", FAIL, str(e)[:70])


# ══════════════════════════════════════════════════════════════════════════════
# 9. Experimento real (gasta LLM)
# ══════════════════════════════════════════════════════════════════════════════

def val_live(modelo: str = "google/gemini-2.5-flash-lite") -> None:
    secao("9. EXPERIMENTO REAL (consome API)")

    from src.runner import run_experiment
    cfg = {
        "model": modelo, "architecture": "sas", "harness": "zero_shot",
        "task": "text_classification", "evaluator": "binary",
        "num_instances": 1, "seed": 42,
    }
    try:
        r = run_experiment(cfg, verbose=False)
    except Exception as e:
        msg = str(e)
        if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            check("live", f"chamada real ({modelo})", WARN,
                  "cota de API esgotada — não é defeito de código")
        else:
            check("live", f"chamada real ({modelo})", FAIL, msg[:90])
        return

    check("live", f"chamada real ({modelo})", OK,
          f"score={r['mean_score']} tokens={r.get('mean_total_tokens')} "
          f"lat={r.get('mean_elapsed_s')}s")

    tem_metricas = all(r.get(k) is not None for k in
                       ("mean_total_tokens", "mean_elapsed_s", "mean_llm_calls"))
    check("live", "instrumentação de custo", OK if tem_metricas else FAIL,
          "tokens, latência e chamadas registrados")

    run_dir = PROJ / "runs" / r["run_id"]
    arquivos = ["config.json", "scores.json", "trace.jsonl"]
    falta = [a for a in arquivos if not (run_dir / a).exists()]
    check("live", "persistência do run", OK if not falta else FAIL,
          f"{run_dir.name}/ com {', '.join(arquivos)}" if not falta else f"faltando {falta}")


# ══════════════════════════════════════════════════════════════════════════════
# Relatório
# ══════════════════════════════════════════════════════════════════════════════

def relatorio() -> int:
    secao("VEREDITO")

    camadas: dict[str, list[str]] = {}
    for camada, _, status, _ in _resultados:
        camadas.setdefault(camada, []).append(status)

    for camada, sts in camadas.items():
        f = sts.count(FAIL)
        w = sts.count(WARN)
        s = sts.count(SKIP)
        total = len(sts)
        if f:
            v = f"{FAIL} ({f}/{total})"
        elif w:
            v = f"{OK} com aviso ({w} aviso(s))"
        elif s == total:
            v = SKIP
        else:
            v = OK
        print(f"  {camada:<15} {v}")

    n_fail = sum(1 for *_, st, _ in _resultados if st == FAIL)
    n_warn = sum(1 for *_, st, _ in _resultados if st == WARN)
    n_ok = sum(1 for *_, st, _ in _resultados if st == OK)
    n_skip = sum(1 for *_, st, _ in _resultados if st == SKIP)

    print(f"\n  {n_ok} passaram · {n_warn} avisos · {n_fail} falhas · {n_skip} pulados")

    if n_fail:
        print("\n  FALHAS:")
        for camada, nome, st, det in _resultados:
            if st == FAIL:
                print(f"    - [{camada}] {nome}: {det}")
    if n_warn:
        print("\n  AVISOS:")
        for camada, nome, st, det in _resultados:
            if st == WARN:
                print(f"    - [{camada}] {nome}: {det}")

    print()
    return 1 if n_fail else 0


def main() -> int:
    args = set(sys.argv[1:])
    tudo = "--all" in args

    print("=" * 66)
    print("  OVERTHINKING MACHINE — validação de integridade")
    print("=" * 66)

    val_ambiente()
    val_codigo()
    val_registros()
    val_comportamentos()
    val_boilerplate()
    val_frontend()

    if tudo or "--api" in args:
        val_api()
    if tudo or "--mcp" in args:
        val_mcp()
    if tudo or "--live" in args:
        val_live()

    return relatorio()


if __name__ == "__main__":
    sys.exit(main())
