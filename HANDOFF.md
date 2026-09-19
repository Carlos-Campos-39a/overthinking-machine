# HANDOFF — Overthinking Machine

Estado em **2026-09-19**. Produção e repositório no mesmo commit.

> **Este arquivo é servido publicamente pelo Vercel.** `*.md` não está no
> `.vercelignore`, então `HANDOFF.md`, `DEPLOY.md`, `README.md` e `turnover.md`
> ficam acessíveis em `https://overthinking-machine-chi.vercel.app/HANDOFF.md`.
> Nada aqui tem segredo — mas não escreva nenhum aqui.

---

## 1. Os três pontos urgentes

### 1.1 Produção em dia, e o auto-deploy funcionando

**Resolvido nesta sessão.** Frontend e backend servem o mesmo commit do
repositório, e `validate_platform.py --producao` dá **17 passaram · 0 avisos ·
0 falhas** — a primeira vez que a camada de produção fecha limpa. Conferido no
ar: `/api/tarefas` responde, a gravação anônima em `/api/library` devolve
**403**, o `escHtml` publicado escapa aspas, o volume está montado e o token de
admin, ativo.

**A causa-raiz do auto-deploy foi corrigida.** O GitHub App do Railway estava
instalado em modo *"Only select repositories"* com **apenas dois** repositórios
(`vc-tracker` e `Fields`) — `overthinking-machine` **não estava na lista**. Sem
acesso, não havia webhook, e cada push ficava no GitHub sem chegar ao ar.

O que foi feito (GitHub → Settings → Applications → Railway App → Configure):
`overthinking-machine` acrescentado à lista, mantendo *"Only select
repositories"* e os outros dois intactos — o Railway recebeu acesso só a este
repositório, não a todos. Depois, no painel do Railway, o aviso mudou de
*"Auto deploy unavailable"* para *"Auto deploy is disabled"*, e o botão
**Enable** foi acionado: agora diz **"Auto deploys when pushed to GitHub"**.

Ressalva: o painel ainda mostra *"Could not load branches. Retry"* mesmo depois
do acesso, e o **Retry não limpa**. Parece cache do painel e não impediu o
deploy automático de funcionar (comprovado por um push logo em seguida), mas se
um push seu não subir, é o primeiro lugar a olhar.

**Conferir sempre**, porque o painel não é fonte confiável:

```bash
curl -s https://overthinking-machine-production.up.railway.app/api/health
```

O campo `commit` tem de bater com `git rev-parse --short HEAD`.

**Se o auto-deploy falhar de novo**, o caminho manual que funciona é o badge
**"Update available"** no canto superior esquerdo da barra lateral do projeto →
**Yes** no diálogo *Update template*. Duas coisas que **não** funcionam e já
custaram tempo: o botão *Check for updates* (Settings → Source) responde
*"You're on the latest version"* mesmo com o serviço vários commits atrás, e
*Redeploy* na aba Deployments reimplanta o **mesmo** commit.

### 1.2 Decisões que dependem de você

1. ~~Acesso do GitHub App do Railway ao repositório~~ — **feito** (ver 1.1).
2. ~~Volume no Railway~~ — **feito**. Volume `overthinking-machine-volume`
   montado em `/data`, com `OTM_DATA_DIR=/data`. O banco saiu de
   `/app/dados/biblioteca.db` (disco do contêiner) para `/data/biblioteca.db`.
   Provado com um redeploy de verdade, não só pelo campo de saúde: uma
   topologia publicada antes do deploy continuou lá depois.
3. ~~`OTM_ADMIN_TOKEN`~~ — **feito por você**; eu não digito segredo em campo
   nenhum, e isso não muda com permissão liberada. Se precisar trocar:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Railway → serviço → *Variables* → `OTM_ADMIN_TOKEN`. Depois, para apagar uma
   topologia: `DELETE /api/biblioteca/{nome}` com o header `X-OTM-Admin`.

### 1.3 `curiosidades.html` foi publicada

`54f44a2` veio de outra sessão de Claude trabalhando nesta mesma árvore: a
página de achados com o benchmark MCP × API (144 agentes headless; taxa de
sucesso praticamente igual nas três interfaces, MCP ~1,9× mais barato). Ela
deixou o push para você decidir, você aprovou, e `/curiosidades` está no ar.

Dois achados desta sessão entraram lá como conteúdo secundário — a probe que se
enganava e a saturação da `triagem_cobranca`. Os números foram conferidos antes
de publicar; o enquadramento diz explicitamente que a plataforma **nunca** leu
ativação de modelo nenhum nessa página, e que o erro foi de rótulo e de
avaliação, não de leitura.

---

## 2. Vulnerabilidade encontrada e corrigida nesta sessão

**XSS armazenado com roubo de chave de API, que estava ativo na instância
pública.** Corrigido em `86aca78` e **implantado** — conferido no ar.

A cadeia completa era:

1. `POST /api/library` aceitava `list[dict]` cru: sem autenticação, sem
   validação, sem teto, sem distinção entre instância local e pública.
2. O conteúdo ia para `library.json`, um arquivo **compartilhado por todos**.
3. `GET /api/library` devolvia isso a qualquer visitante, e `loadLibrary()`
   misturava os cartões recebidos aos do próprio navegador.
4. A interface interpolava `harness`, `arch`, `task` e `name` direto em
   `innerHTML`, sem escapar.
5. As chaves BYOK ficam no `localStorage`.

Resultado: um cartão com `<img src=x onerror="...">` executava no navegador de
todo visitante que abrisse a aba Biblioteca, com acesso à chave de API dele.

**Correção em duas camadas.** No servidor, um modelo pydantic `extra="forbid"`
com teto em cada campo, recusa de gravação anônima na instância hospedada (403)
e teto de 500 cartões. Na interface, `escHtml` passou a escapar aspas também, e
todo ponto que interpola dado de cartão agora escapa; a chave do grupo saiu dos
atributos `onclick` (vai o índice) e o botão de skills usa `data-*` — dentro de
atributo o navegador decodifica a entidade **antes** de o JS ser interpretado,
então escapar HTML não protege uma string JS ali.

Verificado com payload real no navegador: renderiza como texto, zero elementos
injetados, `onerror` não dispara. **Conferido também em produção**: `POST`
anônimo em `/api/library` devolve 403 e o `escHtml` publicado escapa aspas.

**Ficou de fora, e vale revisar:** `renderLeaderboard()`
(`overthinking-machine.html:5114`) tem dois blocos que interpolam em `innerHTML`
sem escapar — `5155-5175` (ramo `experimentRuns`, com `${r.name}` cru inclusive
dentro de `title=`) e `5217-5229` (ramo de referência, que consome a constante
`LB_DATA` da própria página, com `${r.arch}`, `${r.harness}` e `${r.task}`).
Hoje esses dados são locais ou fixos, então não são exploráveis por terceiro;
se algum dia vierem do servidor, o problema volta.

---

## 3. O que foi feito nesta sessão

### Fase 1 — parar de enganar (`0c08b51`)

Quatro pontos em que a plataforma dizia algo falso:

- **Módulo 2 nunca leu ativação de modelo nenhum.** O ramo "real" testava
  `"_real_activations" in dir()` — nome que não existe —, caía sempre na
  simulação e mesmo assim devolvia `mode: "real"`, que a tela escrevia como
  **"Origem: ⚡ Llama real"** sobre ruído gaussiano. Removido. O payload agora
  diz `mode: "simulacao"`, `sintetico: true`, e a tela mostra selo de origem.
- **A probe linear pontuava no próprio treino.** A docstring dizia "acurácia no
  treino (leave-one-out simplificado)" — que se contradiz em uma linha. Medido:
  em **ruído puro**, a probe antiga dava **1,000** nas 5 sementes com n=30
  (0,995 com n=40; 0,937 com n=60), contra acaso de 0,500. Agora é validação
  cruzada 3-fold estratificada, com acurácia fora da amostra.
- **O agente simulado acertava se e somente se o rótulo fosse 1** (bug meu,
  encontrado ao conferir). A acurácia saía ~50% em vez dos ~76% anunciados, e a
  probe de "acerto" lia na verdade o rótulo — separável em todas as camadas,
  inclusive na camada 0. Corrigido: acerta com probabilidade `base_acc`,
  independente do rótulo. A curva agora vai do acaso nas camadas iniciais a 1,0
  no meio da rede, que é o padrão que a página se propõe a ilustrar.
  O payload ganhou `probe_baseline` (classe majoritária) — sem ela a curva não
  se lê.
- **Importar CSV era armadilha silenciosa.** As linhas ficavam no navegador, o
  POST mandava só a quantidade, e o servidor rodava as N primeiras instâncias da
  tarefa **embutida**. A pessoa via um score e acreditava ser o da tarefa dela.
  Bloqueado no modo Real com aviso — e resolvido de vez na Fase 2.

Mais: `mcp.json` da landing em uma linha com botão copiar e os 9 headers; modal
de prompts com os placeholders que existem de verdade; 429 com `como_resolver`;
traceback Python parou de ir para o navegador; Pokédex explica que não existe na
instância pública; tetos de custo em `/api/benchmark` e `/api/prompt-sensitivity`
(que não tinham nenhum) e em `/api/run` para arquitetura embutida.

### Fase 2 — tarefa declarativa (`33a6e25`)

Fecha o objetivo "montar a própria arquitetura e direcionar para o tipo de
tarefa". A plataforma só sabia responder *"qual arquitetura é melhor na minha
tarefa embutida"* — e as embutidas **saturam**: com modelo de raciocínio todas
tiram 1.0 e o experimento não separa nada.

- `src/tasks/tarefa_spec.py` — instrução comum + casos rotulados. Nada executa:
  é texto e rótulo, como uma topologia é nome e template.
- `src/tasks/tarefa_declarativa.py` — o interpretador. **Não** é registrada no
  `TaskRegistry` (nome vazio na classe): uma tarefa declarativa só existe com
  uma spec junto.
- **Prova de expressividade**: `triagem_cobranca` reescrita como spec — gerada
  da *mesma fonte* que a classe, não copiada à mão — produz as mesmas 24
  instâncias, os mesmos **48 prompts byte a byte** e os mesmos **384 scores**.
- **Avisos em vez de recusa** para o que não impede de rodar mas impede de
  acreditar: classes desbalanceadas (com a linha de base calculada), poucos
  casos, gabarito visível dentro do enunciado, entradas duplicadas.
- `GET /api/tarefas` passa a publicar a **linha de base** de cada tarefa. Sem
  ela, 0.80 parece bom mesmo quando o chute fixo dá 0.78.
- `tarefa_spec` em `RunConfig`, `BenchmarkConfig` e `PromptSensitivityConfig` —
  os módulos 1, 3 e 4 rodam na tarefa da pessoa.
- MCP: `listar_tarefas` e `validar_tarefa`; `tarefa_spec` em `rodar_experimento`
  e `rodar_com_topologia`. São **16 ferramentas** agora.

**Decisão:** tarefa **não** vai para a biblioteca pública. Uma topologia é
método e não carrega dado; uma tarefa é feita de casos, e casos são exatamente
onde alguém colaria um extrato de clientes reais sem pensar. A spec viaja só na
requisição.

### Correção de rumo: as citações são reais

O `turnover.md` (de junho) acusava **"Kim et al., 2025"** e **"Lee et al.,
2026"** de serem citações inventadas, e recomendava trocá-las antes do TCC.
**Isso está errado, e o erro foi meu**, de uma sessão anterior. Verificado
direto no arXiv em 19/09/2026:

| citação | título | 1º autor |
|---|---|---|
| `arXiv:2512.08296` | *Towards a Science of Scaling Agent Systems* | Yubin Kim |
| `arXiv:2603.28052` | *Meta-Harness: End-to-End Optimization of Model Harnesses* | Yoonho Lee |

O paper de Kim avalia 260 configurações em 6 benchmarks e 5 abordagens
arquiteturais, e descreve o **efeito de saturação de capacidade** — que é
exatamente o que a plataforma mede, e a origem do Princípio 5. As duas podem ir
para o TCC. `turnover.md` foi corrigido no topo.

**"Bigeard et al., 2025"** (em `src/tasks/finance_agent.py`) continua **não
verificada** — essa parte do alerta segue de pé.

---

## 4. Como testar (tudo offline, custo zero)

```bash
.venv\Scripts\python.exe testar_topologias.py
```
Equivalência das 5 arquiteturas, limites, segurança de template, 168 specs
aleatórias. 22 checagens.

```bash
.venv\Scripts\python.exe testar_tarefas.py
```
A linguagem de tarefas: equivalência (24 instâncias, 48 prompts, 384 scores),
13 recusas, 7 avisos, 9 casos de score. 34 checagens. `--previa` mostra a spec.

```bash
.venv\Scripts\python.exe testar_api.py
```
Tetos de custo, honestidade do módulo 2 e os endpoints de tarefa. 38 checagens,
sem gastar chamada de modelo.

```bash
.venv\Scripts\python.exe validate_platform.py --mcp
```
Suíte geral: 8 camadas nesse modo (as 7 offline + MCP; `--api`, `--live` e
`--producao` acrescentam as suas). A **seção 7 roda `node --check` em todo
`<script>` inline** de toda página `.html` da raiz — varrida por glob, sem lista
para manter, então página nova entra sozinha. Existe porque uma quebra de linha
real dentro de uma string JS já derrubou uma página inteira, em silêncio.

```bash
.venv\Scripts\python.exe validate_platform.py --producao
.venv\Scripts\python.exe testar_mcp.py
```
Conferem o que está **no ar**: commit implantado, rotas, handshake MCP real e as
páginas. `--producao` é o comando que teria pego os cinco commits de atraso
anteriores, e é o que hoje acusa o atraso do item 1.1.

**Estado das suítes agora.** Localmente: `testar_topologias.py`,
`testar_tarefas.py` e `testar_api.py` verdes; `validate_platform.py --mcp` com
40 passaram · 1 aviso · 0 falhas · 2 puladas (o aviso é chave local parecendo
placeholder; as puladas exigem a API em `localhost:8000`).

Em produção: `--producao` dá **15 passaram · 1 aviso · 0 falhas** e
`testar_mcp.py` passa contra a URL pública, com as 16 ferramentas. O único aviso
é a biblioteca sem volume (item 1.2) — a decisão que continua sua.

---

## 5. O que falta, na ordem recomendada

Plano completo em `C:\Users\carlo\.claude\plans\quero-fazer-a-plataforma-giggly-kurzweil.md`.
Ordem: **0 → 1 → 2 → 4 → 5 → 3 → 6 → 7**. Fases 0, 1 e 2 feitas (0 pendente só
no painel do Railway).

### Fase 2, o que ficou faltando
- `tarefa_spec` em `comparar_modelos` e `analisar_prompt` no MCP.
- Um passo sobre tarefa própria no prompt `testar_minha_topologia`.
- **Toda a interface**: cartões de tarefa vindos de `/api/tarefas`, aba "Minha
  tarefa" (colar CSV/JSON → validar → usar) e religar o import de CSV para
  produzir `tarefa_spec`. Hoje a Fase 2 existe inteira no backend e no MCP, e
  nada dela aparece no site.

### Fase 4 — baixáveis e skill agnóstico
Diretório `baixar/` servido pelo Vercel, com `otm-agente.md` (o skill),
`mcp.json`, boilerplate, topologias em JSON, `tarefa-exemplo.json` e o script de
ativações. `gerar_baixaveis.py` monta tudo das **mesmas fontes** que o
`mcp_server.py`, para não divergir. Aposentar `otm-project.skill`. Semear
`PROPOSTAS_OPERACIONAIS` (hoje é código morto, importado em lugar nenhum).

### Fase 5 — landing
Diagrama SVG do fluxo, "Comece em 3 passos", seção "Baixar", aviso da cota
gratuita. Tirar `long-doc-benchmark.html` do deploy (está órfã e no ar).

### Fase 3 — compositor e chaves em todo lugar
Módulo 1 com modelos vindos de `/api/models` (hoje 6 fixos no HTML, então quem
tem chave de Kimi/GLM/Groq não consegue usá-la onde compõe a topologia); módulo
3 com seletor de modelo (hoje `gemini-2.5-flash` fixo); campo "outro modelo";
`config.js` com os **9** provedores que o backend aceita (hoje oferece 6);
harnesses não-expressáveis exibidos travados com o motivo.

### Fase 6 — módulo 2 de primeira classe
Bloco "hook real, na sua máquina", Marks & Tegmark nas referências, recurso MCP
`otm://ativacoes`.

### Fase 7 — robustez
`timeout`/`max_retries` no `llm_factory` (hoje zero); `try/except` por instância
com gravação parcial (hoje um 429 no meio perde a execução inteira e os tokens
já gastos); semáforo de execuções simultâneas; **`reps` + desvio-padrão no
experimento individual** e **custo em US$ em todo resultado** — sem esses dois,
nenhuma comparação é defensável.

---

## 6. Dívidas técnicas confirmadas (auditoria desta sessão)

Todas verificadas no código. Nenhuma é bloqueante hoje; a mais séria já foi
corrigida (seção 2).

1. **`custom_prompts` é editável e ignorado.** A interface deixa editar e salvar
   os prompts (`savePromptEdit`, `overthinking-machine.html:8437-8444`) e os
   envia (`:4538`), mas o servidor não os repassa ao runner (`server.py:117`,
   "reservado para uso futuro"; o dict `config` em `:921-937` não o inclui). No
   modo Real, a pessoa edita prompts que não têm efeito nenhum. É o mesmo tipo
   de mentira que a Fase 1 foi fechar — **próximo candidato óbvio**.
2. **Cancelar execução é fraco.** `DELETE /api/run/{id}` encerra o stream; a
   thread segue consumindo cota até terminar.
3. **Sem teto de execuções simultâneas.** `threading.Thread` cru em 4 lugares;
   `active_runs.pop` fora de `try/finally` (vaza quando o cliente desconecta); e
   `redirect_stdout` é global ao processo, então execuções paralelas **misturam
   os logs** uma da outra.
4. **Modelo sem preço vira custo 0 em silêncio** (`server.py`, catálogo de
   modelos). Deveria ser `null` + "preço não publicado".
5. **Variáveis de ambiente não documentadas.** Fora do `.env.example` e do
   `DEPLOY.md`: `OTM_ADMIN_TOKEN`, `OTM_DATA_DIR`, `OTM_IP_SALT`,
   `OTM_PUB_POR_HORA`/`OTM_PUB_POR_DIA`, `OTM_MCP_HOST`/`OTM_MCP_PORT`/
   `OTM_MCP_TIMEOUT`, `OTM_PROD_API`/`OTM_PROD_SITE`. Documentadas:
   `OTM_ALLOWED_ORIGINS`, `OTM_HOSTED` e `OTM_API_URL`.
6. **`*.md` servido pelo Vercel** — ver o aviso no topo deste arquivo.
7. **`ace`/`mce`/`meta_harness` não são expressáveis** declarativamente, por
   motivos legítimos (`NAO_EXPRESSAVEIS` em `harness_spec.py`). O dado existe no
   endpoint; a interface ainda não os mostra travados.
8. **`README.md` antecede a plataforma web.** Entrou no repositório em
   2026-08-29 (`ecef884`) e nunca mais foi tocado: zero menção a BYOK, MCP,
   Vercel ou Railway. **`DEPLOY.md`** apresenta como "esperado" um
   `biblioteca_persistente: true` que a produção nega (linha 130), e conta
   "4 páginas HTML" (linhas 7 e 135) quando há 7.

### Biblioteca pública: continua sem moderação
`POST /api/biblioteca` (topologias) é público e sem autenticação. Existe: limite
de tamanho, validação estrita antes de gravar, limite por IP (5/h, 20/dia, só o
hash do IP é guardado), teto global de 500 e token de exclusão do autor. **Não
existe:** moderação, reputação ou denúncia. Uma especificação é vetor de injeção
de prompt — não executa código, mas é texto de terceiro enviado ao modelo de
quem a roda, com a chave de quem a roda. A defesa é divulgação: a prévia de
custo zero e o selo de conteúdo de terceiros. `OTM_ADMIN_TOKEN` é a válvula, e
não está configurado.

---

## 7. Limites honestos do que foi provado

A equivalência byte a byte das topologias vale para **5 especificações**, e em
parte por construção: os prompts das propostas foram transcritos do código das
classes. Isso prova que os quatro tipos de estágio **cobrem** as cinco
arquiteturas do paper. **Não** prova que o interpretador está correto para
especificação arbitrária. O teste de propriedade (168 specs aleatórias) é
cobertura adicional — e continua sendo cobertura, não prova.

A equivalência de **tarefa** é mais forte num ponto: a spec é gerada da mesma
fonte da classe, então uma mudança de formatação lá aparece aqui como
divergência. Mas também vale para **uma** tarefa só.

Sobre a avaliação operacional que motivou a Fase 2: em `triagem_cobranca`
(24 casos, gemma-4-31b-it, seed 42, **uma execução, sem repetição nem
desvio-padrão**), SAS tirou 1,000 com 700 tokens e 23,2 s; verificador-precedência
1,000 com 1517 tokens (2,2×) e 67,0 s (2,9×); cascata-de-regras 1,000 com 1701
tokens (2,4×) e 59,8 s. **A tarefa satura**: o score não decide nada, e quem
decide é token e latência. Com n=1 execução, isso **não é estatisticamente
defensável** — é o que a Fase 7 (`reps` + desvio) existe para consertar.
