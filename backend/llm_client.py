"""Client for multiple LLM providers (Qwen, Sarvam) served through OpenAI-compatible APIs.
The assistant only ever asks these models to (a) translate a question into a
structured intent, or (b) narrate an already-computed result - never to invent
numbers itself."""
import os
import ssl
from functools import lru_cache

import httpx
from langchain_openai import ChatOpenAI

from backend.config import (
    DEFAULT_LLM_PROVIDER,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
    SARVAM_API_KEY,
    SARVAM_BASE_URL,
    SARVAM_MODEL,
)


LLM_CONFIGS = {
    "qwen": {
        "model": LLM_MODEL,
        "base_url": LLM_BASE_URL,
        "api_key": LLM_API_KEY,
        "temperature": LLM_TEMPERATURE,
        "timeout": LLM_TIMEOUT_SECONDS,
        "max_retries": LLM_MAX_RETRIES,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "sarvam": {
        "model": SARVAM_MODEL,
        "base_url": SARVAM_BASE_URL,
        "api_key": SARVAM_API_KEY,
        "temperature": LLM_TEMPERATURE,
        "timeout": LLM_TIMEOUT_SECONDS,
        "max_retries": LLM_MAX_RETRIES,
        "extra_body": {},
    },
}


def get_llm_config(provider: str | None = None) -> dict:
    """Get LLM configuration for the specified provider."""
    provider = provider or DEFAULT_LLM_PROVIDER
    if provider not in LLM_CONFIGS:
        raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(LLM_CONFIGS.keys())}")
    
    config = LLM_CONFIGS[provider]
    if not config["model"] or not config["base_url"]:
        raise RuntimeError(
            f"LLM provider '{provider}' is not configured. "
            f"Check your .env file for {provider.upper()}_* settings."
        )
    return config


@lru_cache(maxsize=2)
def get_llm(provider: str | None = None) -> ChatOpenAI:
    """Get LLM client for the specified provider (qwen or sarvam)."""
    config = get_llm_config(provider)
    
    # Check if SSL verification should be disabled (for Sarvam or all providers)
    disable_ssl = os.environ.get("DISABLE_SSL_VERIFICATION", "false").lower() in ("true", "1", "yes")
    
    if disable_ssl:
        # Create a custom httpx client with SSL verification disabled
        http_client = httpx.Client(verify=False)
        return ChatOpenAI(
            model=config["model"],
            base_url=config["base_url"],
            api_key=config["api_key"],
            temperature=config["temperature"],
            timeout=config["timeout"],
            max_retries=config["max_retries"],
            extra_body=config.get("extra_body", {}),
            http_client=http_client,
        )
    
    return ChatOpenAI(
        model=config["model"],
        base_url=config["base_url"],
        api_key=config["api_key"],
        temperature=config["temperature"],
        timeout=config["timeout"],
        max_retries=config["max_retries"],
        extra_body=config.get("extra_body", {}),
    )


def chat(system_prompt: str, user_prompt: str, provider: str | None = None) -> str:
    """Send a single-turn system+user prompt to the specified model and return
    the raw text response. Raises on connection/model errors so callers can
    fall back to guardrail behavior instead of silently guessing."""
    llm = get_llm(provider)
    messages = [
        ("system", system_prompt),
        ("human", user_prompt),
    ]
    response = llm.invoke(messages)
    return response.content
