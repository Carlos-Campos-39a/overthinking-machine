"""
llm_text.py — Extração do texto de uma resposta de LLM.

Nem todo modelo devolve `response.content` como string. Modelos com raciocínio
explícito (Gemma 4, o-series, Claude com thinking, DeepSeek R1…) devolvem uma
LISTA de blocos tipados:

    [{'type': 'thinking', 'thinking': '...raciocínio interno...'},
     {'type': 'text',     'text': 'Paris'}]

Chamar `.content.strip()` nesse caso quebra com
`'list' object has no attribute 'strip'` — e foi exatamente o que impedia os
modelos Gemma de rodar no pipeline.

Além de não quebrar, esta função descarta os blocos de raciocínio e devolve só
a resposta final. Isso importa para a medição: o bloco de thinking não é a
resposta do agente, e incluí-lo faria o avaliador pontuar o rascunho junto com
o resultado — inflando ou destruindo o score por um motivo que não é o modelo.
"""
from __future__ import annotations
from typing import Any


# Blocos que carregam a resposta em si, e não o raciocínio intermediário.
_CHAVES_DE_TEXTO = ("text", "output_text")


def texto_da_resposta(response: Any) -> str:
    """Texto final de uma resposta de LLM, seja ela string ou lista de blocos."""
    return normalizar_conteudo(getattr(response, "content", response))


def normalizar_conteudo(conteudo: Any) -> str:
    if conteudo is None:
        return ""

    if isinstance(conteudo, str):
        return conteudo.strip()

    if isinstance(conteudo, list):
        partes: list[str] = []
        for bloco in conteudo:
            if isinstance(bloco, str):
                partes.append(bloco)
            elif isinstance(bloco, dict):
                tipo = bloco.get("type")
                # thinking / reasoning são rascunho, não resposta
                if tipo in ("thinking", "reasoning", "redacted_thinking"):
                    continue
                for chave in _CHAVES_DE_TEXTO:
                    valor = bloco.get(chave)
                    if isinstance(valor, str) and valor:
                        partes.append(valor)
                        break
        return "\n".join(partes).strip()

    return str(conteudo).strip()
