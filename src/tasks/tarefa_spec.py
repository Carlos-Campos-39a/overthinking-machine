"""
tarefa_spec.py — a linguagem declarativa de tarefas.

Uma tarefa é uma INSTRUÇÃO comum mais uma lista de CASOS rotulados. Nada aqui
executa código de terceiro: uma spec é texto e rótulo, exatamente como uma
topologia é nome, número e template. É o que permite alguém trazer a própria
tarefa para uma instância pública.

POR QUE ISTO EXISTE
-------------------
Até aqui a plataforma respondia "qual das arquiteturas é melhor NA MINHA tarefa
embutida" — e as embutidas saturam: com um modelo de raciocínio, todas tiram
1.0, e o experimento não discrimina nada (é o Princípio 5 acontecendo com a
própria plataforma). Sem tarefa própria, a pessoa não tem como sair desse teto.

Pior: o import de CSV do módulo 1 dava a ILUSÃO de tarefa própria. As linhas
ficavam no navegador, o POST mandava só a quantidade, e o servidor rodava as N
primeiras instâncias da tarefa EMBUTIDA. A pessoa via um score e acreditava que
era o da tarefa dela. Esta spec é o que torna aquele botão verdadeiro.

ONDE UMA SPEC NÃO VAI
---------------------
Tarefa NÃO é publicada na biblioteca compartilhada. Uma topologia é um método e
não carrega dado; uma tarefa é feita de casos, e casos são exatamente onde
alguém colaria, sem pensar, um extrato de clientes reais. A spec viaja só na
requisição de quem a enviou.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Limites
# ─────────────────────────────────────────────────────────────────────────────

MAX_CASOS          = 100
MAX_CHARS_CASO     = 4_000
MAX_CHARS_INSTRUCAO = 8_000
MAX_ROTULOS        = 20
MAX_EXEMPLOS       = 10
MAX_CHARS_TAREFA   = 200_000

LIMITES_TAREFA = {
    "max_casos":           MAX_CASOS,
    "max_chars_caso":      MAX_CHARS_CASO,
    "max_chars_instrucao": MAX_CHARS_INSTRUCAO,
    "max_rotulos":         MAX_ROTULOS,
    "max_exemplos":        MAX_EXEMPLOS,
    "max_chars_tarefa":    MAX_CHARS_TAREFA,
}

# Uma tarefa cujo rótulo majoritário já passa disto não separa arquitetura
# nenhuma: responder sempre a mesma coisa bate qualquer raciocínio.
LIMIAR_DESBALANCEAMENTO = 0.60

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
_SLUG_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")

_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ─────────────────────────────────────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────────────────────────────────────

class Caso(BaseModel):
    model_config = _CONFIG

    id: str
    entrada: str = Field(min_length=1, max_length=MAX_CHARS_CASO)
    esperado: str = Field(min_length=1, max_length=200)
    # Anotação do autor, FORA do prompt. Serve para ler o resultado depois
    # ("onde as arquiteturas se separam?"), nunca para o modelo ver.
    nota: str = Field(default="", max_length=300)

    @field_validator("id")
    @classmethod
    def _id_valido(cls, v: str) -> str:
        if not _SLUG_ID.fullmatch(v):
            raise ValueError(
                f"id de caso '{v}' inválido: minúsculas, dígitos, ponto, _ ou -, até 40 caracteres"
            )
        return v


class Exemplo(BaseModel):
    model_config = _CONFIG

    entrada: str = Field(min_length=1, max_length=MAX_CHARS_CASO)
    saida: str = Field(min_length=1, max_length=200)


class EspecTarefa(BaseModel):
    model_config = _CONFIG

    nome: str
    titulo: str = Field(default="", max_length=120)
    descricao: str = Field(default="", max_length=600)

    # Enunciado comum a todos os casos: a política, a rubrica, o que responder.
    # Vai no começo do prompt de CADA instância, como as tarefas embutidas fazem.
    instrucao: str = Field(default="", max_length=MAX_CHARS_INSTRUCAO)

    # Escolhem o system prompt e a instrução de formato que o harness aplica.
    # Os valores são os que os harnesses embutidos conhecem; qualquer outro cairia
    # num texto genérico em silêncio, então a lista é fechada.
    tipo: Literal["classification", "market_search", "legal_analysis"] = "classification"
    formato_resposta: Literal["single_label", "long_prose", "bullet_points"] = "single_label"
    criterios: list[str] = Field(default_factory=lambda: ["accuracy"], max_length=6)

    rotulos_validos: list[str] = Field(min_length=2)
    casos: list[Caso] = Field(min_length=1)

    # Usados pelo harness few-shot. Ficam fora dos casos de propósito: exemplo
    # que também é caso avaliado é vazamento do gabarito.
    exemplos: list[Exemplo] = Field(default_factory=list)

    @field_validator("nome")
    @classmethod
    def _nome_valido(cls, v: str) -> str:
        if not _SLUG.fullmatch(v):
            raise ValueError(
                f"nome '{v}' inválido: minúsculas, dígitos, _ ou -, de 2 a 40 caracteres"
            )
        return v

    @field_validator("rotulos_validos")
    @classmethod
    def _rotulos_ok(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_ROTULOS:
            raise ValueError(f"no máximo {MAX_ROTULOS} rótulos")
        limpos = [r.strip() for r in v]
        if any(not r for r in limpos):
            raise ValueError("rótulo vazio")
        if len(set(limpos)) != len(limpos):
            raise ValueError("há rótulos repetidos em rotulos_validos")
        for r in limpos:
            if len(r) > 200:
                raise ValueError(f"rótulo '{r[:40]}...' longo demais (máximo 200 caracteres)")
        return limpos

    @field_validator("casos")
    @classmethod
    def _casos_ok(cls, v: list[Caso]) -> list[Caso]:
        if len(v) > MAX_CASOS:
            raise ValueError(f"{len(v)} casos; o teto é {MAX_CASOS}")
        ids = [c.id for c in v]
        if len(set(ids)) != len(ids):
            repetidos = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"ids de caso repetidos: {', '.join(repetidos[:5])}")
        return v

    @field_validator("exemplos")
    @classmethod
    def _exemplos_ok(cls, v: list[Exemplo]) -> list[Exemplo]:
        if len(v) > MAX_EXEMPLOS:
            raise ValueError(f"no máximo {MAX_EXEMPLOS} exemplos")
        return v

    @model_validator(mode="after")
    def _coerencia(self) -> "EspecTarefa":
        validos = set(self.rotulos_validos)

        fora = sorted({c.esperado for c in self.casos} - validos)
        if fora:
            raise ValueError(
                f"casos esperam rótulo que não está em rotulos_validos: {', '.join(fora[:5])}"
            )

        fora_ex = sorted({e.saida for e in self.exemplos} - validos)
        if fora_ex:
            raise ValueError(
                f"exemplos usam rótulo que não está em rotulos_validos: {', '.join(fora_ex[:5])}"
            )

        # Um rótulo que nenhum caso usa infla a aparência de dificuldade sem
        # mudar nada: o modelo nunca é avaliado nele.
        usados = {c.esperado for c in self.casos}
        if len(usados) < 2:
            raise ValueError(
                "todos os casos têm o mesmo rótulo esperado: essa tarefa não mede nada — "
                "responder sempre essa palavra tiraria 1.0"
            )

        tamanho = len(json.dumps(self.model_dump(), ensure_ascii=False))
        if tamanho > MAX_CHARS_TAREFA:
            raise ValueError(f"tarefa com {tamanho} caracteres; o teto é {MAX_CHARS_TAREFA}")
        return self

    # ── leitura ──────────────────────────────────────────────────────────────

    def distribuicao(self) -> dict[str, int]:
        d: dict[str, int] = {}
        for c in self.casos:
            d[c.esperado] = d.get(c.esperado, 0) + 1
        return dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))

    def linha_de_base(self) -> float:
        """
        Score de quem responde SEMPRE o rótulo mais comum.

        É o número que decide se um resultado quer dizer alguma coisa: um
        experimento que tira 0.80 numa tarefa cuja linha de base é 0.78 não
        descobriu nada.
        """
        d = self.distribuicao()
        return max(d.values()) / len(self.casos) if d else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Validação
# ─────────────────────────────────────────────────────────────────────────────

def validar_tarefa(spec: EspecTarefa | dict) -> EspecTarefa:
    """Aceita modelo ou dicionário. Revalida sempre."""
    if isinstance(spec, EspecTarefa):
        return spec
    if not isinstance(spec, dict):
        raise ValueError("a especificação precisa ser um objeto JSON")
    return EspecTarefa.model_validate(spec)


def erros_de_tarefa(spec: Any) -> list[str]:
    """Lista legível de problemas, para a interface e o MCP."""
    from pydantic import ValidationError
    try:
        validar_tarefa(spec)
        return []
    except ValidationError as e:
        msgs = []
        for err in e.errors():
            caminho = ".".join(str(p) for p in err["loc"]) if err["loc"] else "tarefa"
            msgs.append(f"{caminho}: {err['msg']}")
        return msgs
    except ValueError as e:
        return [str(e)]


def avisos_de_tarefa(spec: EspecTarefa) -> list[str]:
    """
    Problemas que NÃO impedem de rodar, mas estragam a leitura do resultado.

    São avisos, não erros, porque a pessoa pode ter um bom motivo — e porque
    recusar a tarefa dela por causa de estatística seria arrogante. O que não se
    pode é deixar ela ler um 0.9 achando que significa algo quando não significa.
    """
    avisos: list[str] = []
    n = len(spec.casos)
    base = spec.linha_de_base()

    if base >= LIMIAR_DESBALANCEAMENTO:
        maior = max(spec.distribuicao().items(), key=lambda kv: kv[1])
        avisos.append(
            f"classes desbalanceadas: responder sempre '{maior[0]}' já tira "
            f"{base:.2f}. Um score abaixo disso é pior que um chute fixo, e um "
            f"pouco acima não prova nada. Equilibre os casos."
        )

    if n < 10:
        avisos.append(
            f"só {n} caso(s): a margem de erro fica maior que a diferença entre "
            f"arquiteturas. Para comparar topologias, 20+ casos."
        )

    sem_exemplo = not spec.exemplos
    if sem_exemplo:
        avisos.append(
            "sem exemplos: o harness few-shot vai rodar igual ao zero-shot, e a "
            "comparação entre os dois não vai medir nada."
        )

    duplicadas = len({c.entrada for c in spec.casos}) < n
    if duplicadas:
        avisos.append("há casos com entrada idêntica — eles medem a mesma coisa duas vezes.")

    # Gabarito dentro do enunciado: o caso responde a si mesmo.
    vazando = [c.id for c in spec.casos if c.esperado.lower() in c.entrada.lower()][:5]
    if vazando:
        avisos.append(
            f"o rótulo esperado aparece dentro da própria entrada em: "
            f"{', '.join(vazando)}. O modelo pode só copiá-lo."
        )
    return avisos


def resumo_da_tarefa(spec: EspecTarefa) -> dict:
    """O que a interface e o MCP mostram antes de gastar uma chamada."""
    return {
        "nome": spec.nome,
        "titulo": spec.titulo or spec.nome,
        "descricao": spec.descricao,
        "casos": len(spec.casos),
        "rotulos": spec.rotulos_validos,
        "distribuicao": spec.distribuicao(),
        "linha_de_base": round(spec.linha_de_base(), 4),
        "exemplos": len(spec.exemplos),
        "avisos": avisos_de_tarefa(spec),
    }
