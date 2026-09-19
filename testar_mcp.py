"""
testar_mcp.py — confere uma conexão MCP com a plataforma, como um cliente de verdade.

    python testar_mcp.py                       # a instância pública
    python testar_mcp.py http://localhost:8000/mcp/
    python testar_mcp.py --chave-google SUA_CHAVE   # confere também o repasse BYOK

Fala o protocolo MCP por HTTP, sem importar nada da plataforma — é exatamente o
que o Claude, o Cursor ou qualquer outro cliente faz. Se isto passa, a URL que a
landing manda colar no mcp.json funciona.

NÃO GASTA CHAMADA DE MODELO. Só usa ferramentas de custo zero: catálogo,
validação e prévia. A chave, se informada, vai apenas no header para conferir
que a plataforma a recebe; nenhum experimento é rodado.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PADRAO = "https://overthinking-machine-production.up.railway.app/mcp/"

_falhas = 0


def check(nome: str, ok: bool, detalhe: str = "") -> bool:
    global _falhas
    if not ok:
        _falhas += 1
    print(f"  [{'ok' if ok else 'XX'}] {nome}" + (f" — {detalhe}" if detalhe else ""))
    return ok


class Cliente:
    def __init__(self, url: str, chaves: dict[str, str]):
        self.url = url
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **chaves,
        }
        self.sessao: str | None = None
        self._id = 0

    def rpc(self, metodo: str, params: dict | None = None) -> dict:
        self._id += 1
        h = dict(self.headers)
        if self.sessao:
            h["Mcp-Session-Id"] = self.sessao
        corpo = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": metodo,
                            "params": params or {}}).encode("utf-8")
        req = urllib.request.Request(self.url, data=corpo, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.sessao = r.headers.get("mcp-session-id") or self.sessao
                texto = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:160]}") from e
        for linha in texto.splitlines():
            if linha.startswith("data: "):
                return json.loads(linha[6:])
        return json.loads(texto)

    def ferramenta(self, nome: str, argumentos: dict) -> dict:
        r = self.rpc("tools/call", {"name": nome, "arguments": argumentos})
        return json.loads(r["result"]["content"][0]["text"])


def main() -> int:
    args = sys.argv[1:]
    chaves: dict[str, str] = {}
    url = PADRAO
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--chave-") and i + 1 < len(args):
            prov = a[len("--chave-"):]
            chaves[f"X-{prov.capitalize()}-Key"] = args[i + 1]
            i += 2
            continue
        if a.startswith("http"):
            url = a if a.endswith("/") else a + "/"
        i += 1

    print("=" * 70)
    print(f"  MCP — {url}")
    print("=" * 70)

    c = Cliente(url, chaves)

    # 1. handshake
    try:
        r = c.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "testar_mcp", "version": "1"}})
        info = r["result"]["serverInfo"]
        check("handshake", True, f"{info['name']} v{info.get('version', '?')}")
        instrucoes = r["result"].get("instructions", "")
    except Exception as e:
        check("handshake", False, str(e)[:120])
        print("\n  Sem handshake não há o que conferir. Se o erro for 404, o MCP não")
        print("  está montado nesta URL; se for 421, é o Host recusado pelo servidor.")
        return 1

    # 2. o que o servidor diz a quem conecta
    check("instruções mencionam topologias próprias",
          "TOPOLOGIAS DEFINIDAS" in instrucoes.upper() or "topologia" in instrucoes.lower())
    check("instruções avisam que a biblioteca é conteúdo de terceiro",
          "DADO A SER EXIBIDO" in instrucoes or "terceiro" in instrucoes.lower())

    # 3. superfície
    ferramentas = {t["name"] for t in c.rpc("tools/list")["result"]["tools"]}
    check("ferramentas", len(ferramentas) >= 16, f"{len(ferramentas)}")
    essenciais = {"listar_capacidades", "validar_topologia", "previa_topologia",
                  "rodar_com_topologia", "rodar_experimento", "estimar_custo",
                  "listar_tarefas", "validar_tarefa"}
    falt = essenciais - ferramentas
    check("ferramentas essenciais presentes", not falt, f"faltam: {sorted(falt)}" if falt else "")

    prompts = {p["name"] for p in c.rpc("prompts/list")["result"]["prompts"]}
    check("prompt guiado testar_minha_topologia", "testar_minha_topologia" in prompts,
          f"{len(prompts)} prompts")

    recursos = {str(x["uri"]) for x in c.rpc("resources/list")["result"]["resources"]}
    check("recursos de metodologia e esquema",
          {"otm://metodologia", "otm://esquema-topologia"} <= recursos, ", ".join(sorted(recursos)))

    # 4. o recurso que ensina a compor — lido da API, então prova o loopback interno
    esquema = c.rpc("resources/read", {"uri": "otm://esquema-topologia"})["result"]["contents"][0]["text"]
    ok_esquema = all(m in esquema for m in ("unico", "paralelo", "debate", "reduzir", "{n:<id>}"))
    check("esquema-topologia completo", ok_esquema,
          f"{len(esquema)} chars" if ok_esquema else "veio o ramo de erro: " + esquema[:100])

    # 5. uma ferramenta de verdade, custo zero
    spec = {"nome": "teste-de-conexao", "estagios": [
        {"id": "p", "tipo": "paralelo", "n": 3, "prompt": "{task_content}"},
        {"id": "d", "tipo": "debate", "n": 3, "rodadas": 2, "prompt": "{pares}"},
        {"id": "r", "tipo": "reduzir", "prompt": "{blocos}", "final": True}]}
    v = c.ferramenta("validar_topologia", {"spec": spec})
    check("validar_topologia", v.get("ok") and v.get("chamadas_por_instancia") == 10,
          f"{v.get('chamadas_por_instancia')} chamadas/instância")

    pv = c.ferramenta("previa_topologia", {"spec": spec})
    check("previa_topologia (custo zero)", len(pv.get("chamadas", [])) == 10 and pv.get("custo_llm") == 0,
          f"{len(pv.get('chamadas', []))} prompts renderizados")

    custo = c.ferramenta("estimar_custo", {"spec": spec, "num_instancias": 40})
    check("estimar_custo usa o validador da plataforma", custo.get("total_chamadas_llm") == 400,
          f"{custo.get('total_chamadas_llm')} chamadas")

    ruim = c.ferramenta("estimar_custo", {"arquitetura": "nao-existe"})
    check("arquitetura inexistente dá erro, não chute", "erro" in ruim)

    bib = c.ferramenta("listar_topologias", {"tipo": "topologia"})
    check("biblioteca responde, com aviso de terceiros no payload",
          bib.get("total", 0) >= 5 and "aviso_conteudo_terceiros" in bib, f"{bib.get('total')} topologias")

    # 6. repasse de chave — só se o usuário informou uma
    caps = c.ferramenta("listar_capacidades", {})
    if chaves:
        provs = [h.split("-")[1].lower() for h in chaves]
        liberados = [m for m in caps.get("modelos_disponiveis", []) if m.split("/")[0] in provs]
        check("a chave do header libera modelos (BYOK atravessa o MCP)", bool(liberados),
              f"{len(liberados)} modelos de {', '.join(provs)}")
    else:
        print("  [--] repasse de chave não conferido — passe --chave-google SUA_CHAVE para testar")

    print("=" * 70)
    print("  tudo certo" if not _falhas else f"  {_falhas} falha(s)")
    print("=" * 70)
    return 1 if _falhas else 0


if __name__ == "__main__":
    sys.exit(main())
