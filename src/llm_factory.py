"""
llm_factory.py — Único ponto de criação de LLMs do projeto.

Formato de modelo: "provider/model-name"

Providers de API fechada (exigem chave no .env):
    openai/gpt-4o-mini
    anthropic/claude-haiku-4-5-20251001
    google/gemini-2.5-flash

Providers de peso aberto rodando localmente (não exigem chave):
    ollama/llama3.1:8b            → servidor Ollama (padrão localhost:11434)
    vllm/Qwen/Qwen2.5-7B-Instruct → servidor vLLM   (padrão localhost:8000)

Providers de peso aberto hospedados (exigem chave, mas dispensam GPU local):
    moonshot/kimi-k2.6            → Moonshot AI (Kimi)
    zai/glm-5                     → Z.ai / Zhipu (GLM)
    groq/llama-3.3-70b-versatile  → Groq
    together/... , openrouter/... , deepinfra/...   → agregadores

Todos falam a API da OpenAI, então reaproveitamos o ChatOpenAI trocando apenas
base_url e chave. Qualquer endereço pode ser sobrescrito por env var
(ex.: MOONSHOT_BASE_URL, ZAI_BASE_URL, OLLAMA_BASE_URL).
"""
from __future__ import annotations
import contextvars
import os
from typing import Any
from langchain_core.language_models import BaseChatModel


# Chaves fornecidas pelo usuário na requisição atual (modo BYOK, plataforma
# publicada). Têm precedência sobre as variáveis de ambiente do servidor, o que
# permite hospedar a plataforma SEM chave nenhuma: cada visitante usa a própria.
#
# É um contextvar e não uma global porque requisições concorrentes de usuários
# diferentes não podem enxergar a chave uma da outra. Threads novas não herdam
# contextvars automaticamente — quem dispara o runner em thread precisa chamar
# set_request_keys() dentro da thread.
_request_keys: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "otm_request_keys", default={}
)


def set_request_keys(keys: dict[str, str]) -> None:
    """Define as chaves do usuário para o contexto atual. {} limpa."""
    _request_keys.set({k: v for k, v in (keys or {}).items() if v})


def get_request_keys() -> dict[str, str]:
    return _request_keys.get()


class LLMFactory:

    # Providers locais: sem chave de API, endereço configurável por env var
    LOCAL_PROVIDERS = {
        "ollama": ("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "vllm":   ("VLLM_BASE_URL",   "http://localhost:8000/v1"),
    }

    # Providers com API compatível com OpenAI, hospedados: exigem chave, mas
    # dispensam GPU. É por aqui que entram os modelos de peso aberto (Kimi, GLM,
    # Llama, Qwen, DeepSeek) sem depender do hardware de quem roda a plataforma.
    #   provider: (env da chave, base_url padrão, env que sobrescreve a url)
    COMPATIBLE_PROVIDERS = {
        "moonshot":   ("MOONSHOT_API_KEY",   "https://api.moonshot.ai/v1",          "MOONSHOT_BASE_URL"),
        "zai":        ("ZAI_API_KEY",        "https://api.z.ai/api/paas/v4",        "ZAI_BASE_URL"),
        "groq":       ("GROQ_API_KEY",       "https://api.groq.com/openai/v1",      "GROQ_BASE_URL"),
        "together":   ("TOGETHER_API_KEY",   "https://api.together.xyz/v1",         "TOGETHER_BASE_URL"),
        "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",        "OPENROUTER_BASE_URL"),
        "deepinfra":  ("DEEPINFRA_API_KEY",  "https://api.deepinfra.com/v1/openai", "DEEPINFRA_BASE_URL"),
    }

    PROVIDERS = {
        "openai":    "langchain_openai.ChatOpenAI",
        "anthropic": "langchain_anthropic.ChatAnthropic",
        "google":    "langchain_google_genai.ChatGoogleGenerativeAI",
        **{p: "langchain_openai.ChatOpenAI" for p in LOCAL_PROVIDERS},
        **{p: "langchain_openai.ChatOpenAI" for p in COMPATIBLE_PROVIDERS},
    }

    @classmethod
    def create(cls, model_string: str, temperature: float = 0.0, **kwargs: Any) -> BaseChatModel:
        provider, model_name = cls._parse(model_string)
        cls._check_api_key(provider)
        return cls._build(provider, model_name, temperature, **kwargs)

    @staticmethod
    def _parse(model_string: str) -> tuple[str, str]:
        if "/" not in model_string:
            raise ValueError(f"Formato inválido: '{model_string}'. Use 'provider/model-name'")
        provider, model_name = model_string.split("/", 1)
        provider = provider.lower()
        if provider not in LLMFactory.PROVIDERS:
            raise ValueError(f"Provider '{provider}' não suportado. Use: {list(LLMFactory.PROVIDERS)}")
        return provider, model_name

    ENV_VARS = {
        "openai":    "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google":    "GOOGLE_API_KEY",
        **{p: spec[0] for p, spec in COMPATIBLE_PROVIDERS.items()},
    }

    @staticmethod
    def api_key_for(provider: str) -> str | None:
        """
        Chave do provider: primeiro a do usuário (BYOK), depois a do ambiente.
        Providers locais não usam chave.
        """
        if provider in LLMFactory.LOCAL_PROVIDERS:
            return None
        do_usuario = get_request_keys().get(provider)
        if do_usuario:
            return do_usuario
        return os.getenv(LLMFactory.ENV_VARS.get(provider, ""))

    @staticmethod
    def _check_api_key(provider: str) -> None:
        # Providers locais não usam chave — o servidor roda na própria máquina
        if provider in LLMFactory.LOCAL_PROVIDERS:
            return
        if not LLMFactory.api_key_for(provider):
            var = LLMFactory.ENV_VARS[provider]
            raise EnvironmentError(
                f"Nenhuma chave para '{provider}'. Informe a sua chave na interface "
                f"(modo BYOK) ou defina {var} no ambiente do servidor."
            )

    @staticmethod
    def base_url(provider: str) -> str | None:
        """Endereço do endpoint, para providers compatíveis com a API da OpenAI."""
        spec = LLMFactory.LOCAL_PROVIDERS.get(provider)
        if spec:
            env_var, default = spec
            return os.getenv(env_var, default)
        spec = LLMFactory.COMPATIBLE_PROVIDERS.get(provider)
        if spec:
            _, default, env_url = spec
            return os.getenv(env_url, default)
        return None

    @staticmethod
    def is_open_weight(provider: str) -> bool:
        """True para providers que servem modelos de peso aberto."""
        return (provider in LLMFactory.LOCAL_PROVIDERS
                or provider in LLMFactory.COMPATIBLE_PROVIDERS)

    @staticmethod
    def _build(provider: str, model_name: str, temperature: float, **kwargs: Any) -> BaseChatModel:
        # A chave é passada explicitamente (e não lida do ambiente pelo próprio
        # cliente) para que a chave do usuário no modo BYOK tenha precedência.
        chave = LLMFactory.api_key_for(provider)

        if provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=model_name, temperature=temperature,
                              api_key=chave, **kwargs)

        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model_name, temperature=temperature,
                                 api_key=chave, **kwargs)

        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(model=model_name, temperature=temperature,
                                          google_api_key=chave, **kwargs)

        elif provider in LLMFactory.LOCAL_PROVIDERS:
            from langchain_openai import ChatOpenAI
            # api_key é obrigatória pelo cliente, mas ignorada pelo servidor local
            return ChatOpenAI(
                model=model_name,
                temperature=temperature,
                base_url=LLMFactory.base_url(provider),
                api_key=os.getenv("LOCAL_LLM_API_KEY", "not-needed"),
                **kwargs,
            )

        elif provider in LLMFactory.COMPATIBLE_PROVIDERS:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model_name,
                temperature=temperature,
                base_url=LLMFactory.base_url(provider),
                api_key=chave,
                **kwargs,
            )

    @classmethod
    def list_supported(cls) -> list[str]:
        return [
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-haiku-4-5-20251001",
            "google/gemini-2.5-flash",
            "google/gemini-2.5-pro",
            # peso aberto — Google serve os Gemma pela mesma chave do Gemini
            "google/gemma-4-31b-it",
            "google/gemma-4-26b-a4b-it",
            # peso aberto hospedado (exigem a chave do respectivo provedor)
            "moonshot/kimi-k2.6",
            "zai/glm-5",
            "groq/llama-3.3-70b-versatile",
            # peso aberto local, se houver Ollama instalado
            "ollama/llama3.1:8b",
            "ollama/qwen2.5:7b",
        ]
