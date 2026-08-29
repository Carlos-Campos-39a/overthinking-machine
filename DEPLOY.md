# Publicando a Overthinking Machine

Arquitetura do deploy — dois serviços, cada um onde faz sentido:

```
   Vercel  (frontend estático)          Railway  (backend Python)
   4 páginas HTML + config.js   ───►    FastAPI + pipeline de agentes
                                        SSE streaming, sem chaves próprias
```

**Modelo de custo: BYOK (bring your own key).** A instância publicada **não tem
chave de API**. Cada visitante informa a própria, guardada apenas no
`localStorage` do navegador dele e enviada por requisição. Consequências:

- você pode publicar sem que ninguém gaste a sua cota;
- a chave de um visitante nunca é persistida no servidor nem vista por outro;
- a plataforma escala sem custo de inferência para você.

---

## Parte 1 — Backend no Railway

### 1.1 Suba o repositório

```bash
git init
git add .
git commit -m "Overthinking Machine — plataforma de benchmarking de agentes"
git branch -M main
git remote add origin https://github.com/<você>/<repo>.git
git push -u origin main
```

Antes de commitar, confirme que os segredos ficaram de fora:

```bash
git status --short | grep -E "\.env$|\.api_keys\.json"    # não deve retornar nada
```

### 1.2 Crie o serviço

No Railway: **New Project → Deploy from GitHub repo** e selecione o repositório.
Ele detecta Python pelo `requirements.txt` e usa o `Procfile`:

```
web: uvicorn server:app --host 0.0.0.0 --port $PORT
```

### 1.3 Variáveis de ambiente

Em **Variables**, defina:

| Variável | Valor | Por quê |
|---|---|---|
| `OTM_HOSTED` | `1` | ativa o modo BYOK — **essencial** |
| `OTM_ALLOWED_ORIGINS` | `https://seu-projeto.vercel.app` | restringe quem chama a API |

**Não defina `GOOGLE_API_KEY`, `OPENAI_API_KEY` nem `ANTHROPIC_API_KEY.`** Se
definir, todo visitante passa a gastar a sua cota — que é justamente o que o
modo BYOK evita.

### 1.4 Gere o domínio

Em **Settings → Networking → Generate Domain**. Anote a URL, algo como
`https://seu-projeto.up.railway.app`.

### 1.5 Verifique

```bash
curl https://seu-projeto.up.railway.app/api/health
curl https://seu-projeto.up.railway.app/api/keys      # deve responder hosted:true
```

---

## Parte 2 — Frontend no Vercel

### 2.1 Aponte o frontend para o backend

Edite `config.js` e troque a URL padrão pela do Railway:

```js
var API_PADRAO = "https://seu-projeto.up.railway.app";
```

Commit e push.

### 2.2 Crie o projeto

No Vercel: **Add New → Project**, selecione o mesmo repositório.

- **Framework Preset:** `Other`
- **Build Command:** deixe vazio
- **Output Directory:** deixe vazio (raiz)

O `.vercelignore` já exclui todo o Python; o `vercel.json` faz `/` abrir a
página principal.

### 2.3 Feche o CORS

Com a URL do Vercel em mãos, volte ao Railway e ajuste
`OTM_ALLOWED_ORIGINS` para o domínio exato. O serviço reinicia sozinho.

---

## Parte 3 — Verificação pós-deploy

1. Abra o site do Vercel. As 4 páginas devem carregar em modo **Mock**.
2. Clique em **🔑 Chaves** e informe uma chave do Gemini.
3. Vá ao **Módulo 4**, troque para **Real** e rode um benchmark pequeno
   (1 modelo, poucas instâncias).
4. Confirme que o resultado traz score, tokens, latência e custo.

Se o modo Real falhar com erro de CORS, `OTM_ALLOWED_ORIGINS` não bate com o
domínio do Vercel (atenção ao `https://` e à ausência de barra no final).

---

## Parte 4 — MCP público (opcional)

Para que agentes de terceiros se conectem à plataforma publicada, há dois
caminhos:

**a) O usuário roda o MCP local apontando para a sua API** — funciona hoje, sem
nada a mais do seu lado:

```json
{
  "mcpServers": {
    "overthinking-machine": {
      "command": "python",
      "args": ["/caminho/mcp_server.py"],
      "env": { "OTM_API_URL": "https://seu-projeto.up.railway.app" }
    }
  }
}
```

**b) Você hospeda o MCP por HTTP** — um segundo serviço no Railway com start
command `python mcp_server.py --http` e `OTM_MCP_HOST=0.0.0.0`. Antes de expor
publicamente, resolva dois pontos que hoje não estão tratados: **autenticação**
(o endpoint está aberto) e **repasse da chave BYOK** (o MCP hoje não encaminha
header de chave do usuário final).

---

## Limitações conhecidas do ambiente hospedado

**Disco efêmero.** O Railway recria o container a cada deploy: `runs/`,
`knowledge_base/` e `pokedex/` são perdidos. Consequências práticas:

- o histórico de execuções não persiste entre deploys;
- os harnesses `ace` e `mce`, que aprendem entre execuções, começam do zero a
  cada reinício.

Para persistir, monte um volume no Railway apontando para esses diretórios ou
troque a escrita por um bucket/banco externo.

**Timeout de requisição.** Experimentos longos (matriz completa, ablação de
prompt com muitas cláusulas) podem exceder o limite de conexão da plataforma.
Prefira lotes menores em produção.

**Cota do visitante.** Um free tier de Gemini esgota na casa do milhar de
chamadas por dia. A UI já avisa o custo estimado antes de rodar — mantenha
esse aviso visível.
