"""
llm_factory.py — Único ponto de criação de LLMs do projeto.

Formato de modelo: "provider/model-name"

Providers de API fechada (exigem chave no .env):
    openai/gpt-4o-mini
    anthropic/claude-haiku-4-5-20251001
    google/gemini-2.5-flash

Providers de peso aberto rodando localmente (não exigem chave):
    ollama/llama3.1:8b          → servidor Ollama  (padrão http://localhost:11434/v1)
    vllm/Qwen/Qwen2.5-7B-Instruct → servidor vLLM  (padrão http://localhost:8000/v1)

Ambos expõem uma API compatível com a da OpenAI, então reaproveitamos o
ChatOpenAI trocando apenas o base_url. Os endereços podem ser sobrescritos
por OLLAMA_BASE_URL / VLLM_BASE_URL no .env.
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

    PROVIDERS = {
        "openai":    "langchain_openai.ChatOpenAI",
        "anthropic": "langchain_anthropic.ChatAnthropic",
        "google":    "langchain_google_genai.ChatGoogleGenerativeAI",
        # peso aberto, servidos localmente via API compatível com OpenAI
        "ollama":    "langchain_openai.ChatOpenAI",
        "vllm":      "langchain_openai.ChatOpenAI",
    }

    # Providers locais: sem chave de API, endereço configurável por env var
    LOCAL_PROVIDERS = {
        "ollama": ("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "vllm":   ("VLLM_BASE_URL",   "http://localhost:8000/v1"),
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
        """Endereço do servidor local para providers de peso aberto."""
        spec = LLMFactory.LOCAL_PROVIDERS.get(provider)
        if not spec:
            return None
        env_var, default = spec
        return os.getenv(env_var, default)

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

    @classmethod
    def list_supported(cls) -> list[str]:
        return [
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-haiku-4-5-20251001",
            "google/gemini-2.5-flash",
            "google/gemini-2.5-pro",
            # peso aberto via Ollama (exemplos — o que estiver instalado localmente)
            "ollama/llama3.1:8b",
            "ollama/qwen2.5:7b",
            "ollama/mistral-small",
            "ollama/gemma2:27b",
        ]
