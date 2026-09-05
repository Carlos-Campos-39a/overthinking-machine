"""
harness_spec.py — a linguagem declarativa de harnesses.

Um harness monta as mensagens que o agente recebe. Declarativamente isso é um
template de system e um de usuário, mais quantos exemplos injetar.

Cobre zero_shot e few_shot caractere a caractere. NÃO cobre:

  ace / mce      precisam de memória em disco entre instâncias, mais chamadas
                 extras de curadoria que o estimador de custo não enxergaria.
  meta_harness   gera código Python e o executa — o oposto da premissa de que
                 nada de terceiro roda.

Esses três seguem existindo como harnesses embutidos; a interface os mostra
como opções travadas, com o motivo escrito. Omiti-los em silêncio faria o
compositor parecer quebrado.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.agents.topologia_spec import MAX_CHARS_PROMPT, renderizar

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")

MAX_EXEMPLOS = 10

PLACEHOLDERS_HARNESS = [
    ("{input}",               "a entrada da instância"),
    ("{format_instructions}", "o formato exigido + os rótulos válidos"),
    ("{exemplos}",            "o bloco de exemplos, se exemplos > 0"),
    ("{task_type}",           "o tipo da tarefa (classification, market_search...)"),
    ("{rotulos_validos}",     "os rótulos aceitos, separados por vírgula"),
    ("{id}",                  "o identificador da instância"),
]


class EspecHarness(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    versao: int = 1
    tipo: Literal["harness"] = "harness"
    nome: str
    titulo: str = Field(default="", max_length=80)
    descricao: str = Field(default="", max_length=500)
    autor: str = Field(default="", max_length=40)

    # None = usa o system da tarefa. Ver a ressalva sobre system_override no
    # HarnessDeclarativo: um system fixo aqui atropelaria a ablação do módulo 3.
    system: str | None = None
    humano: str = Field(max_length=MAX_CHARS_PROMPT)

    # None = todos os exemplos que a tarefa oferecer (é o padrão do FewShot
    # embutido). Um inteiro limita a esse número. Não há risco de inflar o
    # prompt por aqui: os exemplos vêm da tarefa, não da especificação.
    exemplos: int | None = 0
    formato_exemplo: str = Field(
        default="\nExemplo {i}:\nEntrada: {entrada}\nResposta: {saida}\n",
        max_length=400,
    )
    bloco_exemplos: str = Field(
        default="--- EXEMPLOS ---\n{exemplos}\n--- FIM DOS EXEMPLOS ---\n\n",
        max_length=400,
    )

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
        return "".join(c for c in v if c == "\n" or c >= " ")

    @field_validator("exemplos")
    @classmethod
    def _exemplos_ok(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not 0 <= v <= MAX_EXEMPLOS:
            raise ValueError(
                f"exemplos deve ficar entre 0 e {MAX_EXEMPLOS}, ou null para todos "
                f"(recebi {v})"
            )
        return v

    @field_validator("system")
    @classmethod
    def _system_ok(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_CHARS_PROMPT:
            raise ValueError(f"system acima de {MAX_CHARS_PROMPT} caracteres")
        return v

    @field_validator("humano")
    @classmethod
    def _humano_ok(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("o template do usuário não pode ser vazio")
        if "{input}" not in v:
            raise ValueError(
                "o template do usuário precisa conter {input} — sem a entrada da "
                "instância, o modelo responderia sempre a mesma coisa"
            )
        return v


def validar_harness(spec: EspecHarness | dict) -> EspecHarness:
    if isinstance(spec, EspecHarness):
        return spec
    if not isinstance(spec, dict):
        raise ValueError("a especificação precisa ser um objeto JSON")
    return EspecHarness.model_validate(spec)


def erros_de_harness(spec: Any) -> list[str]:
    from pydantic import ValidationError
    try:
        validar_harness(spec)
        return []
    except ValidationError as e:
        return [
            f"{'.'.join(str(p) for p in err['loc']) or 'spec'}: {err['msg']}"
            for err in e.errors()
        ]
    except ValueError as e:
        return [str(e)]


# ─────────────────────────────────────────────────────────────────────────────
# Propostas iniciais — transcritas de manual_harnesses.py
# ─────────────────────────────────────────────────────────────────────────────

ZERO_SHOT = {
    "tipo": "harness",
    "nome": "zero-shot",
    "titulo": "Zero-shot",
    "descricao": "Prompt direto, sem exemplos. Baseline: o piso esperado de desempenho.",
    "autor": "Lee et al. (2026)",
    "humano": "{input}\n\n{format_instructions}",
    "exemplos": 0,
}

FEW_SHOT = {
    "tipo": "harness",
    "nome": "few-shot",
    "titulo": "Few-shot",
    "descricao": (
        "Injeta N exemplos estáticos vindos da tarefa. Exemplos fixos — não "
        "aprendem com execuções anteriores."
    ),
    "autor": "Lee et al. (2026)",
    "humano": "{exemplos}Agora resolva:\n{input}\n\n{format_instructions}",
    # null = todos os exemplos da tarefa, que é o padrão do FewShotHarness.
    "exemplos": None,
}

PROPOSTAS_HARNESS: dict[str, dict] = {
    "zero-shot": ZERO_SHOT,
    "few-shot":  FEW_SHOT,
}

# Harnesses que existem mas não são expressáveis — a interface os mostra
# travados, com este motivo.
NAO_EXPRESSAVEIS = {
    "ace": (
        "Mantém uma base de conhecimento em disco que evolui entre execuções, "
        "e faz chamadas extras de curadoria. Uma especificação declarativa não "
        "tem onde guardar esse estado, e o custo real ficaria invisível."
    ),
    "mce": (
        "Mesma limitação do ACE, com uma etapa a mais de evolução do raciocínio."
    ),
    "meta_harness": (
        "Gera código Python de harness e o executa. É justamente o que a "
        "abordagem declarativa evita para poder aceitar contribuição de terceiros."
    ),
}
