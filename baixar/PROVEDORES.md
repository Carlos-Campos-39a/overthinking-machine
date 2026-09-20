# Provedores aceitos

A instância pública **não tem chave nenhuma**: quem roda traz a sua (BYOK).
Ela vale só para aquela requisição e não é gravada em lugar nenhum.

| provedor | o que é | variável de ambiente | header HTTP | onde obter |
|---|---|---|---|---|
| `google` | Gemini e Gemma | `GOOGLE_API_KEY` | `X-Google-Key` | https://aistudio.google.com/apikey |
| `openai` | GPT | `OPENAI_API_KEY` | `X-Openai-Key` | https://platform.openai.com/api-keys |
| `anthropic` | Claude | `ANTHROPIC_API_KEY` | `X-Anthropic-Key` | https://console.anthropic.com/settings/keys |
| `moonshot` | Kimi (peso aberto) | `MOONSHOT_API_KEY` | `X-Moonshot-Key` | https://platform.moonshot.ai/console/api-keys |
| `zai` | GLM (peso aberto) | `ZAI_API_KEY` | `X-Zai-Key` | https://z.ai/manage-apikey/apikey-list |
| `groq` | Llama/Gemma, inferência rápida | `GROQ_API_KEY` | `X-Groq-Key` | https://console.groq.com/keys |
| `together` | agregador de peso aberto | `TOGETHER_API_KEY` | `X-Together-Key` | https://api.together.ai/settings/api-keys |
| `openrouter` | agregador multi-provedor | `OPENROUTER_API_KEY` | `X-Openrouter-Key` | https://openrouter.ai/keys |
| `deepinfra` | agregador de peso aberto | `DEEPINFRA_API_KEY` | `X-Deepinfra-Key` | https://deepinfra.com/dash/api_keys |

## Dois modos, e eles não se misturam

- **MCP por HTTP** (instância hospedada): a chave vai no header, em cada
  requisição. É o único jeito de uma instância pública rodar sem ter chave.
- **MCP por stdio** (na sua máquina): a chave vem do ambiente, como de costume.

## Peso aberto sem GPU

Estes provedores servem modelos de peso aberto por API: `moonshot`, `zai`, `groq`, `together`, `openrouter`, `deepinfra`. Gemma sai pela mesma chave do Gemini.

Para rodar localmente, sem chave nenhuma: `ollama`, `vllm` — só no modo local, porque a instância hospedada não alcança a sua máquina.

## Cota gratuita engana

O nível gratuito do `gemini-2.5-flash` é de ~20 requisições/dia. Uma matriz
de 5 arquiteturas × 10 instâncias estoura isso antes da segunda célula. Os
Gemma usam a mesma chave, com cota separada. `groq` costuma ser a via mais
folgada para começar sem gastar.
