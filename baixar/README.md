# Baixar

Material para usar a Overthinking Machine a partir do seu agente, do seu
editor ou do seu terminal. Tudo gerado do código — se algo aqui divergir
da plataforma, a plataforma vale.

| arquivo | para quê |
|---|---|
| [`otm-agente.md`](otm-agente.md) | o guia completo, em Markdown puro: Agent Skill, regra do Cursor, `AGENTS.md` ou system prompt |
| [`mcp.json`](mcp.json) | conexão pronta para colar no cliente MCP |
| [`PROVEDORES.md`](PROVEDORES.md) | os 9 provedores, a variável de ambiente e o header de cada um |
| [`tarefa-exemplo.json`](tarefa-exemplo.json) | uma tarefa declarativa completa, para copiar e editar |
| [`ativacoes/README.md`](ativacoes/README.md) | como rodar o hook de verdade na sua máquina |

## Topologias (8)

Prontas para `rodar_com_topologia` ou `POST /api/run`. As cinco primeiras
são as arquiteturas de Kim et al. (2025); as outras nasceram de um caso
de operação real (triagem de cobrança com política de precedência).

- [`topologias/cascata-de-regras.json`](topologias/cascata-de-regras.json)
- [`topologias/centralized.json`](topologias/centralized.json)
- [`topologias/decentralized.json`](topologias/decentralized.json)
- [`topologias/hybrid.json`](topologias/hybrid.json)
- [`topologias/independent.json`](topologias/independent.json)
- [`topologias/sas.json`](topologias/sas.json)
- [`topologias/verificador-precedencia.json`](topologias/verificador-precedencia.json)
- [`topologias/voto-triplo.json`](topologias/voto-triplo.json)

## Harnesses (2)

- [`harnesses/few-shot.json`](harnesses/few-shot.json)
- [`harnesses/zero-shot.json`](harnesses/zero-shot.json)

## O que NÃO está aqui

O boilerplate em Python (definir tarefa como classe, rodar pela CLI) fica
no repositório, em [`boilerplate/`](https://github.com/Carlos-Campos-39a/overthinking-machine/tree/main/boilerplate) — este
diretório carrega só Markdown e JSON, porque o deploy do site ignora
`*.py` em qualquer profundidade.

Desde a tarefa declarativa, aliás, escrever Python virou opcional: dá
para trazer a sua tarefa como JSON, pelo site ou pelo MCP.
