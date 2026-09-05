"""
topologia_spec.py — a linguagem declarativa de topologias.

Uma topologia é um PIPELINE de estágios. Cada estágio faz uma ou mais chamadas
ao LLM e entrega sua saída ao próximo. Quatro tipos bastam para reproduzir as
cinco arquiteturas de Kim et al. (2025) — essa é a prova de que o formato é
expressivo o suficiente:

    sas            unico
    independent    paralelo -> reduzir
    centralized    unico -> paralelo(dividir) -> reduzir
    decentralized  paralelo -> debate -> reduzir
    hybrid         unico -> paralelo(dividir) -> debate -> reduzir

NADA AQUI EXECUTA CÓDIGO DE TERCEIRO. Uma spec é dado: nomes, números e
templates de prompt. É o que permite aceitar topologias de visitantes numa
instância pública.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Limites
#
# A plataforma não tinha limite nenhum: num_instances, reps e meta_budget eram
# todos ilimitados. Uma spec piora isso, porque estágios x n x rodadas x
# instâncias se multiplicam. Estes tetos são servidos em GET /api/limites para
# que a interface e o MCP nunca os repitam à mão.
# ─────────────────────────────────────────────────────────────────────────────

MAX_ESTAGIOS               = 8
MAX_N_POR_ESTAGIO          = 8
MAX_RODADAS                = 3
MAX_CHAMADAS_POR_INSTANCIA = 40
MAX_CHARS_PROMPT           = 4000
MAX_CHARS_SPEC             = 20_000
MAX_INSTANCIAS             = 50
MAX_CHAMADAS_POR_RUN       = 400
MAX_ESPECS_BIBLIOTECA      = 500

LIMITES = {
    "max_estagios":               MAX_ESTAGIOS,
    "max_n_por_estagio":          MAX_N_POR_ESTAGIO,
    "max_rodadas":                MAX_RODADAS,
    "max_chamadas_por_instancia": MAX_CHAMADAS_POR_INSTANCIA,
    "max_chars_prompt":           MAX_CHARS_PROMPT,
    "max_chars_spec":             MAX_CHARS_SPEC,
    "max_instancias":             MAX_INSTANCIAS,
    "max_chamadas_por_run":       MAX_CHAMADAS_POR_RUN,
    "max_especs_biblioteca":      MAX_ESPECS_BIBLIOTECA,
}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
_SLUG_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


# ─────────────────────────────────────────────────────────────────────────────
# Renderização de template
# ─────────────────────────────────────────────────────────────────────────────

# Substituição por lista branca. NÃO usar str.format():
#   1. prompts legitimamente contêm chaves (exemplos de JSON na saída esperada),
#      e str.format levantaria KeyError neles;
#   2. str.format permite travessia de atributo — "{0.__class__.__mro__}" —, o
#      que seria uma fuga num sistema cuja premissa é que nada de terceiro roda.
# Chave desconhecida fica literal: não quebra e não vaza.
_PAT_PLACEHOLDER = re.compile(r"\{([a-z_]+(?::[a-z0-9_-]+)?)\}")


def renderizar(template: str, contexto: dict[str, Any]) -> str:
    """Troca {chave} pelos valores do contexto; deixa o resto literal."""
    def _troca(m: "re.Match[str]") -> str:
        valor = contexto.get(m.group(1))
        return m.group(0) if valor is None else str(valor)
    return _PAT_PLACEHOLDER.sub(_troca, template or "")


# Vocabulário aceito nos templates. É o mesmo já exibido ao usuário no modal de
# prompts do módulo 1, para que a cola do compositor seja a cola do modal.
PLACEHOLDERS_TOPOLOGIA = [
    ("{task_content}",      "a tarefa original, como veio do harness"),
    ("{system_content}",    "o system prompt vindo do harness"),
    ("{n}",                 "quantos agentes há neste estágio"),
    ("{i}",                 "índice deste agente (1..n)"),
    ("{papel}",             "a persona deste agente, se houver"),
    ("{subtarefa}",         "a fatia da decomposição destinada a este agente"),
    ("{resposta_anterior}", "a saída do estágio consumido"),
    ("{pares}",             "as respostas dos outros agentes (só em debate)"),
    ("{blocos}",            "todas as respostas do estágio consumido, formatadas"),
    ("{rodada}",            "a rodada atual do debate"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────────────────────────────────────

# extra="forbid" é a defesa principal do endpoint público de escrita: campo
# desconhecido é recusado antes de qualquer coisa tocar o disco.
_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)

# O que cada tipo de estágio entrega ao seguinte.
PRODUZ: dict[str, str] = {
    "unico":    "texto",
    "paralelo": "lista",
    "debate":   "lista",
    "reduzir":  "texto",
}


class Estagio(BaseModel):
    model_config = _CONFIG

    id: str
    tipo: Literal["unico", "paralelo", "debate", "reduzir"]
    rotulo: str = Field(default="", max_length=60)

    n: int = 1
    rodadas: int = 1

    # id do estágio consumido. None = o estágio imediatamente anterior (ou a
    # própria tarefa, se este for o primeiro).
    de: str | None = None

    # Só em paralelo: fatia a saída do estágio consumido em n subtarefas.
    dividir: bool = False

    papeis: list[str] = Field(default_factory=list)

    system: str | None = None
    prompt: str = Field(default="", max_length=MAX_CHARS_PROMPT)

    # Invoca o LLM com a lista de mensagens ORIGINAL do harness, sem reconstruir
    # nada. É o que torna sas/independent idênticos byte a byte às classes
    # embutidas, que chamam llm.invoke(messages) direto.
    entrada_bruta: bool = False

    formato_par:   str = Field(default="--- Resposta do Agente {j} ---\n{saida}", max_length=400)
    formato_bloco: str = Field(default="=== Agente {j} ===\n{saida}", max_length=400)

    final: bool = False

    @field_validator("id")
    @classmethod
    def _id_valido(cls, v: str) -> str:
        if not _SLUG_ID.fullmatch(v):
            raise ValueError(
                f"id '{v}' inválido: use minúsculas, dígitos, _ ou -, de 1 a 32 caracteres"
            )
        return v

    @field_validator("papeis")
    @classmethod
    def _papeis_ok(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_N_POR_ESTAGIO:
            raise ValueError(f"no máximo {MAX_N_POR_ESTAGIO} papéis")
        for p in v:
            if len(p) > 200:
                raise ValueError("cada papel deve ter no máximo 200 caracteres")
        return v

    @field_validator("system")
    @classmethod
    def _system_ok(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_CHARS_PROMPT:
            raise ValueError(f"system acima de {MAX_CHARS_PROMPT} caracteres")
        return v

    @model_validator(mode="after")
    def _coerencia(self) -> "Estagio":
        if self.tipo in ("unico", "reduzir"):
            if self.n != 1:
                raise ValueError(
                    f"estágio '{self.id}' ({self.tipo}) faz uma chamada só: n deve ser 1"
                )
        else:
            if not 2 <= self.n <= MAX_N_POR_ESTAGIO:
                raise ValueError(
                    f"estágio '{self.id}': n deve ficar entre 2 e {MAX_N_POR_ESTAGIO} "
                    f"(recebi {self.n})"
                )

        if self.tipo == "debate":
            if not 1 <= self.rodadas <= MAX_RODADAS:
                raise ValueError(
                    f"estágio '{self.id}': rodadas deve ficar entre 1 e {MAX_RODADAS} "
                    f"(recebi {self.rodadas})"
                )
        elif self.rodadas != 1:
            raise ValueError(f"'rodadas' só existe em estágio de debate (veja '{self.id}')")

        if self.dividir and self.tipo != "paralelo":
            raise ValueError(f"'dividir' só existe em estágio paralelo (veja '{self.id}')")

        if self.entrada_bruta:
            if self.tipo not in ("unico", "paralelo"):
                raise ValueError(
                    f"'entrada_bruta' só vale em unico ou paralelo (veja '{self.id}'): "
                    f"um debate não tem o que dizer sem o contexto dos pares"
                )
            if self.dividir:
                raise ValueError(
                    f"estágio '{self.id}': entrada_bruta e dividir se excluem — ou passa "
                    f"as mensagens originais, ou monta um prompt com a subtarefa"
                )

        if not self.entrada_bruta and not self.prompt.strip():
            raise ValueError(
                f"estágio '{self.id}' precisa de um prompt (ou de entrada_bruta, para "
                f"repassar as mensagens originais sem alterá-las)"
            )
        return self

    def chamadas(self) -> int:
        return {
            "unico":    1,
            "paralelo": self.n,
            "debate":   self.n * self.rodadas,
            "reduzir":  1,
        }[self.tipo]


class EspecTopologia(BaseModel):
    model_config = _CONFIG

    versao: int = 1
    tipo: Literal["topologia"] = "topologia"
    nome: str
    titulo: str = Field(default="", max_length=80)
    descricao: str = Field(default="", max_length=500)
    autor: str = Field(default="", max_length=40)
    estagios: list[Estagio]

    @field_validator("nome")
    @classmethod
    def _nome_valido(cls, v: str) -> str:
        if not _SLUG.fullmatch(v):
            raise ValueError(
                f"nome '{v}' inválido: use minúsculas, dígitos, _ ou -, de 2 a 40 caracteres"
            )
        return v

    @field_validator("titulo", "descricao", "autor")
    @classmethod
    def _sem_controle(cls, v: str) -> str:
        # Estes três campos são exibidos a outras pessoas na biblioteca.
        return "".join(c for c in v if c == "\n" or c >= " ")

    @model_validator(mode="after")
    def _estrutura(self) -> "EspecTopologia":
        est = self.estagios
        if not est:
            raise ValueError("a topologia precisa de ao menos um estágio")
        if len(est) > MAX_ESTAGIOS:
            raise ValueError(f"no máximo {MAX_ESTAGIOS} estágios (recebi {len(est)})")

        vistos: dict[str, str] = {}   # id -> o que produz
        for pos, e in enumerate(est):
            if e.id in vistos:
                raise ValueError(f"id de estágio repetido: '{e.id}'")

            if e.de is None:
                origem = est[pos - 1].id if pos else None
            else:
                if e.de not in vistos:
                    # Só olhar para trás mantém o grafo acíclico por construção.
                    raise ValueError(
                        f"estágio '{e.id}' consome '{e.de}', que não foi declarado antes dele"
                    )
                origem = e.de

            produz_origem = vistos.get(origem) if origem else None

            if e.tipo in ("debate", "reduzir") and produz_origem != "lista":
                de_txt = f"'{origem}'" if origem else "a tarefa"
                raise ValueError(
                    f"estágio '{e.id}' ({e.tipo}) precisa consumir várias respostas, mas "
                    f"{de_txt} produz uma só — coloque um estágio paralelo antes"
                )

            if e.dividir and produz_origem != "texto":
                raise ValueError(
                    f"estágio '{e.id}' usa dividir, que fatia UMA resposta em n partes, "
                    f"mas o estágio consumido já produz várias"
                )

            vistos[e.id] = PRODUZ[e.tipo]

        finais = [e.id for e in est if e.final]
        if len(finais) != 1:
            raise ValueError(
                f"marque exatamente um estágio como final "
                f"(encontrei {len(finais)}: {finais or 'nenhum'})"
            )
        if PRODUZ[next(e.tipo for e in est if e.final)] != "texto":
            raise ValueError(
                "o estágio final precisa entregar uma resposta só — use unico ou reduzir"
            )

        total = chamadas_por_instancia(self)
        if total > MAX_CHAMADAS_POR_INSTANCIA:
            raise ValueError(
                f"esta topologia faz {total} chamadas por instância; o teto é "
                f"{MAX_CHAMADAS_POR_INSTANCIA}. Reduza n, rodadas ou estágios."
            )
        return self


def chamadas_por_instancia(spec: EspecTopologia) -> int:
    """Fonte única da estimativa de custo — validador, API, UI e MCP usam esta."""
    return sum(e.chamadas() for e in spec.estagios)


def validar_topologia(spec: EspecTopologia | dict) -> EspecTopologia:
    """Aceita modelo ou dicionário. Revalida sempre, inclusive vindo do banco."""
    if isinstance(spec, EspecTopologia):
        return spec
    if not isinstance(spec, dict):
        raise ValueError("a especificação precisa ser um objeto JSON")
    return EspecTopologia.model_validate(spec)


def erros_de(spec: Any) -> list[str]:
    """Lista legível de problemas, para a interface e o MCP."""
    from pydantic import ValidationError
    try:
        validar_topologia(spec)
        return []
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            caminho = ".".join(str(p) for p in err["loc"]) if err["loc"] else "spec"
            msgs.append(f"{caminho}: {err['msg']}")
        return msgs
    except ValueError as e:
        return [str(e)]
