# HANDOFF — Overthinking Machine

Estado em 2026-09-05, commit `30da54a`. Árvore de trabalho limpa.

---

## O ponto mais urgente

**O frontend publicado está à frente do backend publicado.**

| | commit | tem a aba nova? |
|---|---|---|
| Vercel (frontend) | atual | sim — `labtab-esp`, `esp-wrap`, `switchLabTab` no ar |
| Railway (backend) | anterior | não — `/api/arquiteturas` e `/api/biblioteca` devolvem **404** |

Quem abrir a aba **Montar topologia** no site hoje vê a interface montar e as
chamadas falharem. O laboratório antigo continua funcionando normalmente.

O auto-deploy do Railway já parou de acompanhar os pushes uma vez nesta sessão.
A correção é manual, no painel do serviço: banner **"Update available"** →
**Yes**. Depois, conferir:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://overthinking-machine-production.up.railway.app/api/arquiteturas
```

Esperado `200`. Enquanto der 404, o deploy não subiu.

---

## O que foi feito

A plataforma tinha 5 arquiteturas e 5 harnesses fixos: respondia *"qual das 5 é
melhor"*, nunca *"a minha é melhor que as 5?"*. Agora qualquer pessoa monta a
própria topologia arrastando na interface, ou submete por MCP, e roda no mesmo
esqueleto de medição. As 5 viraram **propostas iniciais** editáveis.

### A linguagem

Pipeline de estágios, quatro tipos: `unico`, `paralelo`, `debate`, `reduzir`.
Nada de terceiro executa — uma especificação é só nome, número e template de
prompt. É o que permite aceitar contribuição numa instância pública.

**Prova de expressividade** (roda offline, custo zero): as 5 arquiteturas
reescritas como especificação produzem os **mesmos prompts, byte a byte**, que
as classes Python.

| topologia | chamadas | prompts |
|---|---|---|
| sas | 1 | idênticos |
| independent | 4 | idênticos |
| centralized | 5 | idênticos |
| decentralized | 7 | idênticos |
| hybrid | 8 | idênticos |

As contagens conferem com o dicionário fixo do MCP (`mcp_server.py`), o que
cruza duas fontes que antes ninguém comparava.

### Superfície nova

**10 endpoints**, todos de custo zero em chamadas ao modelo:

```
GET    /api/arquiteturas          catálogo (mata o hardcode do front e do MCP)
GET    /api/harnesses             idem, com os não-expressáveis e o motivo
GET    /api/limites               os tetos, para ninguém repeti-los à mão
POST   /api/especificacoes/validar
POST   /api/especificacoes/previa renderiza TODOS os prompts sem chamar o modelo
GET    /api/biblioteca            lista o acervo
GET    /api/biblioteca/saude      denuncia acervo volátil
GET    /api/biblioteca/{nome}
POST   /api/biblioteca            publica (devolve token de exclusão)
DELETE /api/biblioteca/{nome}     token do autor ou OTM_ADMIN_TOKEN
```

**6 ferramentas MCP**: `listar_topologias`, `obter_topologia`,
`validar_topologia`, `previa_topologia`, `publicar_topologia`,
`rodar_com_topologia`. Além disso `listar_capacidades` passou a **ler** o
catálogo em vez de repetir a lista fixa.

**Aba no módulo 1**: paleta arrastável, pipeline reordenável, diagrama SVG,
custo ao vivo, e Validar · Prévia · Rodar · Publicar. Aditiva — o laboratório
existente não foi reestruturado, e volta como `grid` ao alternar de aba.

### Decisões que valem conhecer antes de mexer

**Renderização de template por lista branca, não `str.format()`.** Dois motivos:
prompts contêm chaves legítimas (exemplos de JSON na saída esperada), e
`str.format` permite travessia de atributo — `{0.__class__.__mro__}` seria uma
fuga real num sistema cujo pilar é não executar nada de terceiro. Há teste que
confirma que isso renderiza literalmente.

**`entrada_bruta`.** `SingleAgentSystem` e `IndependentMAS` chamam
`llm.invoke(messages)` com a lista original do harness. Reconstruir um par
[System, Human] daria prompt diferente sempre que o harness emitisse mais de
duas mensagens. Essa flag é a diferença entre "parecido" e "idêntico".

**Limites de custo, que não existiam em lugar nenhum da API.** Teto por estágio,
por instância (40) e por execução (400), recusados com HTTP **400 antes** do
stream — não como evento de erro dentro do SSE. `num_instances` também ganhou
teto (50), o que é mudança de comportamento para todo mundo, não só para specs.

---

## Bugs reais corrigidos no caminho

1. **`runner.py`** checava `isinstance(harness, (AceHarness, MceHarness))` para
   atualizar memória. Um harness com estado vindo de terceiros seria ignorado
   **em silêncio** — memória que nunca atualiza, sem erro nenhum. Agora é
   `hasattr`.
2. **`validate_platform.py`** exigia *exatamente* 5 arquiteturas (`==`). Passou
   a ser superconjunto, senão cada extensão vira falsa falha.
3. **Os dois harnesses não estavam sendo semeados** na biblioteca: faltava a
   chave `tipo`, e um `except: continue` engolia o erro. A semeadura agora
   reclama alto.
4. Três divergências de prompt que eu tinha assumido erradas, achadas só porque
   a comparação é byte a byte: `centralized` e `hybrid` têm prompts de
   decomposição **diferentes**; `decentralized` põe a persona **no fim**; o
   debate rotula a rodada anterior como `n-1`.

---

## Como testar

Tudo offline, sem gastar chamada:

```bash
.venv\Scripts\python.exe testar_topologias.py
```

21 verificações: equivalência das 5, cada limite recusando, segurança do
template, e 168 especificações aleatórias.

Ver os prompts que uma topologia enviaria — é assim que se lê uma topologia de
terceiro antes de gastar a própria chave:

```bash
.venv\Scripts\python.exe testar_topologias.py --previa centralized
```

Suíte geral da plataforma (23 checagens):

```bash
.venv\Scripts\python.exe validate_platform.py
```

Na interface, com a API local:

```bash
.venv\Scripts\python.exe -m uvicorn server:app --port 8000
```

---

## Arquivos tocados

### Novos

| arquivo | papel |
|---|---|
| `src/agents/topologia_spec.py` | a linguagem: modelos, limites, renderização |
| `src/agents/agente_declarativo.py` | o interpretador (`AgentBase`) |
| `src/agents/propostas_iniciais.py` | as 5 arquiteturas como especificação |
| `src/agents/parse_subtarefas.py` | parser extraído (estava duplicado) |
| `src/agents/equivalencia.py` | LLM falso + comparação byte a byte |
| `src/harnesses/harness_spec.py` | a linguagem de harness + 2 propostas |
| `src/harnesses/harness_declarativo.py` | o interpretador de harness |
| `src/biblioteca.py` | acervo em SQLite + guarda-corpos |
| `testar_topologias.py` | verificação de custo zero |

### Modificados

| arquivo | o que mudou |
|---|---|
| `src/runner.py` | aceita `topologia_spec`/`harness_spec`; `isinstance`→`hasattr`; registra `architecture_used` |
| `src/agents/agent_factory.py` | registra `declarativo`; `descrever_arquiteturas()` |
| `src/agents/centralized.py`, `hybrid.py` | delegam ao parser compartilhado |
| `server.py` | 10 endpoints; `RunConfig` com as specs; `_validar_orcamento` |
| `mcp_server.py` | 6 ferramentas; catálogo dinâmico; `_get` aceita params |
| `overthinking-machine.html` | aba, compositor, `startRealExperiment(extraCfg)` |
| `validate_platform.py` | asserção de superconjunto |
| `.gitignore` | `dados/` |

---

## O que falta

### Bloqueante para a aba funcionar em produção

- [ ] **Subir o Railway para `30da54a`** (ver o topo deste documento).

### Decisões pendentes — são suas, não minhas

#### 1. Volume no Railway

A biblioteca compartilhada grava em SQLite sob `OTM_DATA_DIR`. **O disco do
Railway é recriado a cada deploy.** Sem um volume montado, o acervo funciona em
desenvolvimento e é apagado em produção a cada push — o pior modo de falha
possível, porque não dá erro.

O código já denuncia a situação: aviso no startup (`aviso_de_persistencia()`) e
em `GET /api/biblioteca/saude`, com `volume_configurado: false`.

Para resolver, no painel do Railway: criar um volume, montar em `/data`, e
definir `OTM_DATA_DIR=/data`. As 7 propostas iniciais são re-semeadas sozinhas
mesmo num volume zerado, então elas nunca somem — mas o que os visitantes
publicarem, sim.

**Alternativas, se não quiser volume:** deixar a biblioteca em memória e assumir
que é efêmera (basta não configurar nada, e o aviso já diz isso a quem olhar), ou
trocar por Postgres — a interface `Biblioteca` em `src/biblioteca.py` foi feita
com esse Protocol justamente para a troca ser localizada.

#### 2. Moderação

`POST /api/biblioteca` é **público e sem autenticação**. Existe hoje:

- limite de tamanho (20 KB) e validação estrita antes de gravar — campo que o
  schema não conhece some antes de tocar o disco
- limite por IP: 5/hora e 20/dia (só o hash do IP é guardado)
- teto global de 500 (recusa em vez de despejar — despejar deixaria alguém
  apagar o trabalho alheio por inundação)
- token de exclusão do autor, e `OTM_ADMIN_TOKEN` como válvula

**O que isso não resolve, e precisa ser decisão consciente:**

- **Não há moderação nenhuma.** Qualquer um publica, e aparece para todos. Sem
  conta, sem reputação, sem denúncia. A única alavanca é `OTM_ADMIN_TOKEN` +
  exclusão manual — e ele **não está configurado** hoje.
- **O limite por IP é contornável.** Segura inundação acidental, não alguém
  determinado.
- **Uma especificação é vetor de injeção de prompt.** Não executa código, mas é
  texto de terceiro enviado ao LLM de quem a roda, com a chave de quem a roda. A
  defesa é divulgação, não prevenção: a prévia de custo zero, o selo de conteúdo
  de terceiros na interface, e o aviso repetido em três lugares no MCP
  (docstring, payload e instruções do servidor).
- **O custo de saída é ilimitado.** Os tetos limitam o número de chamadas e o
  tamanho da entrada; uma spec que peça respostas gigantes custa dinheiro real
  dentro dos limites.

**Caminhos possíveis:** manter aberto e definir `OTM_ADMIN_TOKEN` para poder
limpar; exigir aprovação sua antes de aparecer (uma coluna `aprovada` na tabela);
ou fechar a publicação e aceitar contribuição só por pull request no
repositório, o que troca conveniência por revisão humana.

### Pendências anteriores, ainda abertas

- **MCP público** sem autenticação e sem repasse de chave BYOK
  (`DEPLOY.md` já registra). `rodar_com_topologia` contra a instância hospedada
  falha por falta de chave.
- **`POST /api/library`** (cartões de execução, feature separada) continua sem
  validação e sem persistir — ficou fora do escopo deste trabalho.
- **Cancelamento de execução é fraco:** `DELETE /api/run/{id}` só interrompe o
  stream; a thread segue consumindo cota até terminar.
- **`ace`/`mce`/`meta_harness` não são expressáveis** declarativamente, por
  motivos legítimos documentados em `harness_spec.py` (`NAO_EXPRESSAVEIS`). A
  interface deve mostrá-los travados com o motivo — hoje o dado existe no
  endpoint, mas a aba ainda não o exibe.

---

## Limites honestos do que foi provado

A igualdade byte a byte vale para **5 especificações**, e em parte por
construção: os prompts das propostas foram transcritos do código das classes.
Isso prova que os quatro tipos de estágio **cobrem** as cinco arquiteturas do
paper. **Não** prova que o interpretador está correto para especificação
arbitrária.

O teste de propriedade (168 specs aleatórias, sem exceção, contagem sempre
batendo com a estimativa) é cobertura adicional — e continua sendo cobertura,
não prova.
