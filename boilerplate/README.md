# Overthinking Machine — Boilerplate

Ponto de partida para medir, na **sua** tarefa, quatro decisões de projeto que
normalmente são tomadas no chute:

| Pergunta | Módulo |
|---|---|
| Qual arquitetura de agentes usar? | 1 · Arquitetura |
| O que acontece dentro do modelo? | 2 · Rede Neural |
| Que parte do meu prompt importa? | 3 · Prompt |
| Qual modelo devo usar? | 4 · Modelos |

Você pode usar pela interface web, pela CLI, ou — o caminho mais interessante —
**conectando o seu próprio agente via MCP**, para que ele conduza os
experimentos seguindo a metodologia sem você ter que lembrar dela.

---

## 1. Instalação

```bash
git clone <repo> && cd Projeto
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

Crie um `.env` na raiz com pelo menos uma chave:

```
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

Para rodar modelos **open-weight** sem custo de API, instale o
[Ollama](https://ollama.com) e baixe um modelo:

```bash
ollama pull llama3.1:8b
```

A plataforma detecta sozinha o que estiver instalado. Se o Ollama estiver em
outro endereço, defina `OLLAMA_BASE_URL` no `.env`.

---

## 2. Defina a sua tarefa

```bash
cp boilerplate/minha_tarefa.py src/tasks/minha_tarefa.py
```

Edite o arquivo (as instruções estão nos comentários) e confirme o registro:

```bash
python run.py --list-tasks
```

O ponto que mais causa resultado enganoso: **declare `ROTULOS_VALIDOS`** se a
sua tarefa tem vocabulário fechado. Sem isso o modelo responde algo correto mas
fora do vocabulário e o avaliador conta como erro — você mede formatação
achando que está medindo capacidade.

---

## 3. Suba os serviços

```bash
python -m uvicorn server:app --port 8000      # API
python -m http.server 8731                    # interface web (opcional)
```

---

## 4. Conecte o seu agente via MCP

O servidor MCP expõe a plataforma como ferramentas e **carrega a metodologia
junto**: as descrições das ferramentas e os prompts guiados levam o agente a
congelar variáveis, validar barato antes de gastar caro e reportar custo junto
com score.

### Claude Code

```bash
claude mcp add overthinking-machine -- python /caminho/para/Projeto/mcp_server.py
```

### Claude Desktop / Cursor — `mcp.json`

```json
{
  "mcpServers": {
    "overthinking-machine": {
      "command": "python",
      "args": ["/caminho/para/Projeto/mcp_server.py"],
      "env": { "OTM_API_URL": "http://localhost:8000" }
    }
  }
}
```

### Contra uma instância publicada

Aponte `OTM_API_URL` para o seu domínio — o resto é igual:

```json
"env": { "OTM_API_URL": "https://sua-plataforma.com" }
```

Ou sirva o próprio MCP por HTTP, para clientes que suportam transporte remoto:

```bash
python mcp_server.py --http        # http://127.0.0.1:8765/mcp
```

### O que o agente ganha

**Ferramentas**

| Ferramenta | O que faz |
|---|---|
| `listar_capacidades` | arquiteturas, harnesses, tarefas e modelos realmente disponíveis |
| `estimar_custo` | quantas chamadas de LLM antes de gastar |
| `validar_pipeline` | Etapa 1: as 5 arquiteturas com n=1 (~25 chamadas) |
| `rodar_experimento` | uma célula: score + tokens + latência |
| `comparar_modelos` | módulo 4, com fronteira de Pareto e recomendação |
| `dividir_prompt` | cláusulas do prompt, sem gastar LLM |
| `analisar_prompt` | módulo 3: ablação leave-one-out |

**Prompts guiados** — `protocolo_validacao`, `escolher_arquitetura`,
`escolher_modelo`, `otimizar_prompt`

**Recursos** — `otm://metodologia`, `otm://referencias`

Exemplo de uso, em linguagem natural:

> "Use a overthinking-machine para descobrir qual modelo usar na tarefa
> minha_tarefa. Siga o protocolo e me mostre o custo antes de rodar."

---

## 5. O protocolo

Rode nesta ordem. **Só avance quando a etapa anterior passar.**

### Etapa 1 — o pipeline executa? (~25 chamadas)

```bash
for A in sas independent centralized decentralized hybrid; do
  python run.py -a $A -H zero_shot -t minha_tarefa -e binary -n 1 --seed 42
done
```

Um erro de configuração descoberto aqui custou 25 chamadas. Descoberto na
Etapa 4, custaria centenas.

### Etapa 2 — os harnesses persistem memória? (~25 chamadas)

```bash
python run.py -a sas -H zero_shot -t minha_tarefa -e binary -n 2
python run.py -a sas -H few_shot  -t minha_tarefa -e binary -n 2
python run.py -a sas -H ace       -t minha_tarefa -e binary -n 4
python run.py -a sas -H mce       -t minha_tarefa -e binary -n 4
```

`ace` e `mce` usam n=4 de propósito: o curador só dispara ao fechar um lote de
5, e com n=4 o flush final garante pelo menos um ciclo de atualização.
Confirme que `knowledge_base/` e `pokedex/` foram criados com conteúdo.

### Etapa 3 — o avaliador caro funciona?

Se usar `llm_judge`, rode 2 instâncias e **abra o `trace.jsonl`**. Confira que
o campo `feedback` tem texto real do juiz. Se vier `0.5` repetido em tudo, o
parsing da nota falhou e o experimento "funciona" sem medir nada.

### Etapa 4 — a matriz

```bash
for A in sas independent centralized decentralized hybrid; do
  for H in zero_shot ace; do
    python run.py -a $A -H $H -t minha_tarefa -e binary -n 10 --seed 42
  done
done
```

---

## 6. Como não tirar a conclusão errada

**Congele tudo menos uma variável.** Comparar duas configurações que diferem em
modelo *e* harness não mede nenhum dos dois. Use sempre a mesma `--seed`: ela
determina quais instâncias são sorteadas.

**Justifique o n.** Com n=3, um erro é 33% do score — não distingue nada. Com
n=10, é 10%. Escolha pelo que precisa detectar, não por hábito.

**Repita antes de concluir.** Com `reps=1` é impossível separar variância
estocástica do modelo de diferença real. Na nossa própria validação, o único
erro de uma matriz mudou de arquitetura entre duas execuções idênticas — o que
invalidaria qualquer conclusão tirada de uma execução só.

**Score sozinho não é resultado.** Reporte tokens, latência e custo. Duas
configurações com o mesmo score não são equivalentes se uma custa 20× mais.

**Cuidado com o efeito teto.** Se todas as arquiteturas empatam perto de 1.0, a
conclusão não é "arquitetura não importa" — é "esta tarefa não mede
arquitetura". Kim et al. (2025) mostram que a coordenação multi-agente tem
retorno decrescente quando o baseline de agente único já é alto. Aumente a
dificuldade ou troque de avaliador.

---

## 7. Onde ficam os resultados

```
runs/<run_id>/
  config.json    configuração exata (para reproduzir)
  scores.json    score, tokens, latência, chamadas — agregado e por instância
  trace.jsonl    uma linha por instância: prompt, resposta, nota, trace do agente
```

O `trace.jsonl` é o que responde *por que* um score foi baixo. Antes de teorizar
sobre um resultado ruim, abra o trace e leia o que o modelo de fato respondeu.

---

## Referências

- **KIM, Y. et al.** *Towards a Science of Scaling Agent Systems.* arXiv:2512.08296, 2025.
- **LEE, Y. et al.** *Meta-Harness: End-to-End Optimization of Model Harnesses.* arXiv:2603.28052, 2026.
- **CEMRI, M. et al.** *Why Do Multi-Agent LLM Systems Fail?* arXiv:2503.13657, 2025.
- **ZHANG, Q. et al.** *Agentic Context Engineering (ACE).* arXiv:2510.04618, 2025.
- **YE, H. et al.** *Meta Context Engineering (MCE).* arXiv:2601.21557, 2026.
