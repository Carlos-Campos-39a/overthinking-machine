"""
biblioteca.py — acervo compartilhado de topologias e harnesses.

Guarda especificações que qualquer visitante publica e qualquer visitante usa.
SQLite da biblioteca padrão: sem dependência nova.

ONDE OS DADOS FICAM
    OTM_DATA_DIR aponta o diretório. No Railway isso precisa ser um VOLUME
    montado — o disco do contêiner é recriado a cada deploy. Sem volume, tudo
    funciona em desenvolvimento e some em produção, que é o pior modo de falha
    possível; por isso `saude()` denuncia a situação e o servidor avisa no
    startup.

O QUE ESTES GUARDA-CORPOS FAZEM
    tamanho     recusa corpo grande antes de analisar
    validação   grava o modelo revalidado, nunca o corpo cru: campo que o
                schema não conhece é descartado antes de tocar o disco
    taxa        limita publicações por IP em 1h e 24h
    teto        recusa acima de MAX_ESPECS_BIBLIOTECA — recusar é melhor que
                despejar, senão bastaria inundar para apagar o trabalho alheio
    token       quem publica recebe um token de exclusão, uma única vez

O QUE ELES NÃO FAZEM
    Não há moderação. Qualquer pessoa publica, e o que ela publicar aparece
    para todo mundo. Não há conta, reputação nem denúncia — a única alavanca é
    OTM_ADMIN_TOKEN e exclusão manual. E o limite por IP segura inundação
    acidental, não alguém determinado.

    Uma especificação também é vetor de injeção de prompt: não executa código,
    mas é texto de terceiro enviado ao LLM de quem a roda, com a chave de quem
    a roda. Contra isso a defesa é divulgação — a prévia de custo zero, o selo
    de conteúdo de terceiros na interface e o aviso no MCP.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from src.agents.topologia_spec import (
    MAX_CHARS_SPEC,
    MAX_ESPECS_BIBLIOTECA,
    chamadas_por_instancia,
    validar_topologia,
)
from src.harnesses.harness_spec import validar_harness

PROJETO = Path(__file__).parent.parent

PUB_POR_HORA = int(os.getenv("OTM_PUB_POR_HORA", "5"))
PUB_POR_DIA = int(os.getenv("OTM_PUB_POR_DIA", "20"))


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_ip(ip: str) -> str:
    """Nunca guardamos o IP — só um hash com sal, para contar publicações."""
    sal = os.getenv("OTM_IP_SALT", "otm-sal-padrao")
    return hashlib.sha256(f"{sal}:{ip}".encode()).hexdigest()[:32]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ErroBiblioteca(Exception):
    """Erro previsto, com mensagem já apresentável ao usuário."""

    def __init__(self, mensagem: str, codigo: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo


# ─────────────────────────────────────────────────────────────────────────────
# Validação — o portão por onde tudo passa antes de ser gravado
# ─────────────────────────────────────────────────────────────────────────────

def normalizar(spec: Any) -> tuple[dict, str, int]:
    """
    Valida e devolve (spec limpa, tipo, chamadas por instância).

    A spec devolvida é o `model_dump` do modelo, não o corpo recebido: qualquer
    campo que o schema não conheça desaparece aqui.
    """
    if not isinstance(spec, dict):
        raise ErroBiblioteca("a especificação precisa ser um objeto JSON")

    bruto = json.dumps(spec, ensure_ascii=False)
    if len(bruto) > MAX_CHARS_SPEC:
        raise ErroBiblioteca(
            f"especificação com {len(bruto)} caracteres; o teto é {MAX_CHARS_SPEC}"
        )

    tipo = spec.get("tipo", "topologia")
    try:
        if tipo == "harness":
            modelo = validar_harness(spec)
            return modelo.model_dump(), "harness", 0
        modelo = validar_topologia(spec)
        return modelo.model_dump(), "topologia", chamadas_por_instancia(modelo)
    except ErroBiblioteca:
        raise
    except Exception as e:
        raise ErroBiblioteca(f"especificação inválida: {e}") from e


# ─────────────────────────────────────────────────────────────────────────────

class Biblioteca(Protocol):
    def listar(self, tipo: str | None = None, busca: str = "",
               limite: int = 50, deslocamento: int = 0) -> list[dict]: ...
    def obter(self, nome: str) -> dict | None: ...
    def publicar(self, spec: Any, autor: str, ip: str) -> dict: ...
    def excluir(self, nome: str, token: str = "", admin: bool = False) -> bool: ...
    def registrar_uso(self, nome: str) -> None: ...
    def saude(self) -> dict: ...


_ESQUEMA = """
CREATE TABLE IF NOT EXISTS especificacoes (
  nome          TEXT PRIMARY KEY,
  tipo          TEXT NOT NULL,
  titulo        TEXT NOT NULL DEFAULT '',
  descricao     TEXT NOT NULL DEFAULT '',
  autor         TEXT NOT NULL DEFAULT '',
  spec_json     TEXT NOT NULL,
  chamadas_inst INTEGER NOT NULL DEFAULT 0,
  origem        TEXT NOT NULL DEFAULT 'usuario',
  token_hash    TEXT NOT NULL DEFAULT '',
  ip_hash       TEXT NOT NULL DEFAULT '',
  criado_em     TEXT NOT NULL,
  usos          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_esp_tipo ON especificacoes(tipo, criado_em DESC);

CREATE TABLE IF NOT EXISTS publicacoes (
  ip_hash   TEXT NOT NULL,
  criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pub_ip ON publicacoes(ip_hash, criado_em);
"""


class BibliotecaSQLite:
    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as con:
            con.executescript(_ESQUEMA)
        self._semear()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.caminho, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con

    # ── semeadura ────────────────────────────────────────────────────────────

    def _semear(self) -> None:
        """
        Repõe as propostas iniciais. INSERT OR IGNORE: se o volume for zerado,
        elas voltam; se já existirem, nada muda. Assim o acervo nunca aparece
        vazio, mesmo tendo perdido o conteúdo de usuário.
        """
        from src.agents.propostas_iniciais import PROPOSTAS_INICIAIS
        from src.harnesses.harness_spec import PROPOSTAS_HARNESS

        with self._con() as con:
            for spec in list(PROPOSTAS_INICIAIS.values()) + list(PROPOSTAS_HARNESS.values()):
                try:
                    limpa, tipo, chamadas = normalizar(spec)
                except ErroBiblioteca as e:
                    # Uma proposta quebrada não pode derrubar o acervo, mas
                    # sumir calada é pior: foi assim que os dois harnesses
                    # deixaram de ser semeados sem ninguém perceber.
                    print(f"[biblioteca] proposta '{spec.get('nome', '?')}' não pôde "
                          f"ser semeada: {e.mensagem}")
                    continue
                con.execute(
                    "INSERT OR IGNORE INTO especificacoes "
                    "(nome, tipo, titulo, descricao, autor, spec_json, chamadas_inst,"
                    " origem, token_hash, ip_hash, criado_em, usos)"
                    " VALUES (?,?,?,?,?,?,?,'proposta_inicial','','',?,0)",
                    (limpa["nome"], tipo, limpa.get("titulo", ""), limpa.get("descricao", ""),
                     limpa.get("autor", ""), json.dumps(limpa, ensure_ascii=False),
                     chamadas, _agora()),
                )

    # ── leitura ──────────────────────────────────────────────────────────────

    def listar(self, tipo=None, busca="", limite=50, deslocamento=0) -> list[dict]:
        sql = ("SELECT nome, tipo, titulo, descricao, autor, chamadas_inst, origem,"
               " criado_em, usos FROM especificacoes WHERE 1=1")
        args: list[Any] = []
        if tipo:
            sql += " AND tipo = ?"
            args.append(tipo)
        if busca:
            sql += " AND (nome LIKE ? OR titulo LIKE ? OR descricao LIKE ?)"
            args += [f"%{busca}%"] * 3
        # Propostas iniciais primeiro: são o ponto de partida recomendado.
        sql += " ORDER BY (origem='proposta_inicial') DESC, criado_em DESC LIMIT ? OFFSET ?"
        args += [min(limite, 200), deslocamento]
        with self._con() as con:
            return [dict(r) for r in con.execute(sql, args)]

    def obter(self, nome: str) -> dict | None:
        with self._con() as con:
            r = con.execute(
                "SELECT nome, tipo, titulo, descricao, autor, spec_json, chamadas_inst,"
                " origem, criado_em, usos FROM especificacoes WHERE nome = ?", (nome,)
            ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["spec"] = json.loads(d.pop("spec_json"))
        return d

    # ── escrita ──────────────────────────────────────────────────────────────

    def publicar(self, spec: Any, autor: str, ip: str) -> dict:
        limpa, tipo, chamadas = normalizar(spec)

        if autor:
            limpa["autor"] = autor[:40]

        ip_h = hash_ip(ip or "desconhecido")
        agora = datetime.now(timezone.utc)

        with self._con() as con:
            total = con.execute("SELECT COUNT(*) FROM especificacoes").fetchone()[0]
            if total >= MAX_ESPECS_BIBLIOTECA:
                raise ErroBiblioteca(
                    f"a biblioteca atingiu o limite de {MAX_ESPECS_BIBLIOTECA} "
                    f"especificações. Fale com quem mantém a instância.", 503
                )

            for janela, teto, rotulo in (
                (timedelta(hours=1), PUB_POR_HORA, "hora"),
                (timedelta(days=1), PUB_POR_DIA, "dia"),
            ):
                corte = (agora - janela).isoformat()
                n = con.execute(
                    "SELECT COUNT(*) FROM publicacoes WHERE ip_hash=? AND criado_em > ?",
                    (ip_h, corte),
                ).fetchone()[0]
                if n >= teto:
                    raise ErroBiblioteca(
                        f"limite de {teto} publicações por {rotulo} atingido. "
                        f"Tente mais tarde.", 429
                    )

            # Nomes nunca colidem: sufixo numérico. Sem endpoint de atualização,
            # ninguém sobrescreve o trabalho de outra pessoa.
            base = limpa["nome"]
            nome = base
            i = 2
            while con.execute("SELECT 1 FROM especificacoes WHERE nome=?", (nome,)).fetchone():
                nome = f"{base}-{i}"
                i += 1
            limpa["nome"] = nome

            token = secrets.token_urlsafe(16)
            con.execute(
                "INSERT INTO especificacoes (nome, tipo, titulo, descricao, autor,"
                " spec_json, chamadas_inst, origem, token_hash, ip_hash, criado_em, usos)"
                " VALUES (?,?,?,?,?,?,?,'usuario',?,?,?,0)",
                (nome, tipo, limpa.get("titulo", ""), limpa.get("descricao", ""),
                 limpa.get("autor", ""), json.dumps(limpa, ensure_ascii=False),
                 chamadas, _hash_token(token), ip_h, _agora()),
            )
            con.execute("INSERT INTO publicacoes (ip_hash, criado_em) VALUES (?,?)",
                        (ip_h, _agora()))

        return {
            "nome": nome,
            "tipo": tipo,
            "chamadas_inst": chamadas,
            "token_exclusao": token,
            "aviso": ("Guarde o token: ele aparece uma única vez e é o único jeito "
                      "de excluir esta especificação depois."),
        }

    def excluir(self, nome: str, token: str = "", admin: bool = False) -> bool:
        with self._con() as con:
            r = con.execute(
                "SELECT token_hash, origem FROM especificacoes WHERE nome=?", (nome,)
            ).fetchone()
            if not r:
                raise ErroBiblioteca("especificação não encontrada", 404)
            if not admin:
                if r["origem"] == "proposta_inicial":
                    raise ErroBiblioteca("propostas iniciais não podem ser excluídas", 403)
                if not token or not secrets.compare_digest(_hash_token(token), r["token_hash"]):
                    raise ErroBiblioteca("token de exclusão inválido", 403)
            con.execute("DELETE FROM especificacoes WHERE nome=?", (nome,))
        return True

    def registrar_uso(self, nome: str) -> None:
        with self._con() as con:
            con.execute("UPDATE especificacoes SET usos = usos + 1 WHERE nome=?", (nome,))

    def saude(self) -> dict:
        with self._con() as con:
            n = con.execute("SELECT COUNT(*) FROM especificacoes").fetchone()[0]
            u = con.execute(
                "SELECT COUNT(*) FROM especificacoes WHERE origem='usuario'"
            ).fetchone()[0]
        return {
            "persistente": True,
            "caminho": str(self.caminho),
            "volume_configurado": bool(os.getenv("OTM_DATA_DIR")),
            "total": n,
            "de_usuarios": u,
            "teto": MAX_ESPECS_BIBLIOTECA,
        }


class BibliotecaMemoria:
    """Reserva para quando o diretório não é gravável. Some ao reiniciar."""

    def __init__(self) -> None:
        self._itens: dict[str, dict] = {}
        from src.agents.propostas_iniciais import PROPOSTAS_INICIAIS
        from src.harnesses.harness_spec import PROPOSTAS_HARNESS
        for spec in list(PROPOSTAS_INICIAIS.values()) + list(PROPOSTAS_HARNESS.values()):
            try:
                limpa, tipo, chamadas = normalizar(spec)
            except ErroBiblioteca:
                continue
            self._itens[limpa["nome"]] = {
                "nome": limpa["nome"], "tipo": tipo, "titulo": limpa.get("titulo", ""),
                "descricao": limpa.get("descricao", ""), "autor": limpa.get("autor", ""),
                "spec": limpa, "chamadas_inst": chamadas, "origem": "proposta_inicial",
                "criado_em": _agora(), "usos": 0,
            }

    def listar(self, tipo=None, busca="", limite=50, deslocamento=0) -> list[dict]:
        itens = [
            {k: v for k, v in i.items() if k != "spec"}
            for i in self._itens.values()
            if (not tipo or i["tipo"] == tipo)
            and (not busca or busca.lower() in (i["nome"] + i["titulo"] + i["descricao"]).lower())
        ]
        itens.sort(key=lambda i: (i["origem"] != "proposta_inicial", i["criado_em"]))
        return itens[deslocamento:deslocamento + limite]

    def obter(self, nome: str) -> dict | None:
        return self._itens.get(nome)

    def publicar(self, spec: Any, autor: str, ip: str) -> dict:
        limpa, tipo, chamadas = normalizar(spec)
        if autor:
            limpa["autor"] = autor[:40]
        base = limpa["nome"]; nome = base; i = 2
        while nome in self._itens:
            nome = f"{base}-{i}"; i += 1
        limpa["nome"] = nome
        token = secrets.token_urlsafe(16)
        self._itens[nome] = {
            "nome": nome, "tipo": tipo, "titulo": limpa.get("titulo", ""),
            "descricao": limpa.get("descricao", ""), "autor": limpa.get("autor", ""),
            "spec": limpa, "chamadas_inst": chamadas, "origem": "usuario",
            "criado_em": _agora(), "usos": 0, "_token": _hash_token(token),
        }
        return {"nome": nome, "tipo": tipo, "chamadas_inst": chamadas,
                "token_exclusao": token,
                "aviso": "Instância sem disco persistente: isto some ao reiniciar."}

    def excluir(self, nome: str, token: str = "", admin: bool = False) -> bool:
        item = self._itens.get(nome)
        if not item:
            raise ErroBiblioteca("especificação não encontrada", 404)
        if not admin:
            if item["origem"] == "proposta_inicial":
                raise ErroBiblioteca("propostas iniciais não podem ser excluídas", 403)
            if not token or not secrets.compare_digest(_hash_token(token), item.get("_token", "")):
                raise ErroBiblioteca("token de exclusão inválido", 403)
        del self._itens[nome]
        return True

    def registrar_uso(self, nome: str) -> None:
        if nome in self._itens:
            self._itens[nome]["usos"] += 1

    def saude(self) -> dict:
        return {
            "persistente": False,
            "caminho": "(memória)",
            "volume_configurado": False,
            "total": len(self._itens),
            "de_usuarios": sum(1 for i in self._itens.values() if i["origem"] == "usuario"),
            "teto": MAX_ESPECS_BIBLIOTECA,
            "aviso": "Sem disco gravável: o acervo se perde ao reiniciar.",
        }


_instancia: Biblioteca | None = None


def obter_biblioteca() -> Biblioteca:
    global _instancia
    if _instancia is None:
        destino = Path(os.getenv("OTM_DATA_DIR", str(PROJETO / "dados")))
        try:
            _instancia = BibliotecaSQLite(destino / "biblioteca.db")
        except Exception as e:
            print(f"[biblioteca] sem disco gravável em {destino} ({e}); usando memória")
            _instancia = BibliotecaMemoria()
    return _instancia


def aviso_de_persistencia() -> str | None:
    """Alerta de startup quando a instância é pública e o acervo é volátil."""
    if os.getenv("OTM_HOSTED") == "1" and not os.getenv("OTM_DATA_DIR"):
        return (
            "ATENCAO: OTM_HOSTED=1 sem OTM_DATA_DIR. A biblioteca compartilhada "
            "sera apagada a cada deploy. Monte um volume e aponte OTM_DATA_DIR "
            "para ele."
        )
    return None
