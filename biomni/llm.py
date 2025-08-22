import os
import re
import time
from typing import Literal, Optional, Any, Callable
from langchain_core.language_models.chat_models import BaseChatModel

SourceType = Literal["OpenAI", "AzureOpenAI", "Anthropic", "Ollama", "Gemini", "Bedrock", "Groq", "Custom"]


def _wrap_llm_with_retry(llm: BaseChatModel, max_attempts: int = 8) -> BaseChatModel:
    """Wrap llm.invoke with robust 429-aware retry logic (respects Retry-After).

    - Honors HTTP 429 Retry-After header when available.
    - Parses 'retry after <seconds>' phrases in error messages.
    - Uses exponential backoff (cap ~120s) when header/hint not present.
    """

    original_invoke: Callable[..., Any] = llm.invoke
    original_ainvoke: Callable[..., Any] | None = getattr(llm, "ainvoke", None)

    def _parse_retry_after(e: Exception) -> int | None:
        # Try OpenAI-style rate limit error
        try:
            import openai as _openai
            if isinstance(e, getattr(_openai, "RateLimitError", tuple())):
                resp = getattr(e, "response", None)
                if resp is not None:
                    # OpenAI v1 style
                    headers = getattr(resp, "headers", {}) or {}
                    ra = headers.get("Retry-After") or headers.get("retry-after")
                    if ra:
                        try:
                            return int(ra)
                        except Exception:
                            pass
        except Exception:
            pass

        # Azure/Generic: parse from message
        m = re.search(r"retry\s+after\s+(\d+)", str(e), re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
        return None

    def _is_rate_limit(e: Exception) -> bool:
        text = str(e).lower()
        if "429" in text or "rate limit" in text or "throttl" in text:
            return True
        # Try to match OpenAI RateLimitError class
        try:
            import openai as _openai
            if isinstance(e, getattr(_openai, "RateLimitError", tuple())):
                return True
        except Exception:
            pass
        # HTTPX/requests style status_code
        status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
        return status == 429

    def _retry_invoke(*args: Any, **kwargs: Any):
        delay = 5
        attempt = 0
        last_err = None
        while attempt < max_attempts:
            try:
                return original_invoke(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if not _is_rate_limit(e):
                    raise
                wait = _parse_retry_after(e)
                if wait is None:
                    wait = min(delay, 120)
                    delay = min(int(delay * 1.8) + 1, 120)
                time.sleep(max(wait, 1))
                attempt += 1
        # Exhausted retries
        raise last_err

    # Monkey-patch invoke with retrying version
    setattr(llm, "invoke", _retry_invoke)
    if original_ainvoke is not None:
        async def _retry_ainvoke(*args: Any, **kwargs: Any):  # type: ignore
            delay = 5
            attempt = 0
            last_err = None
            while attempt < max_attempts:
                try:
                    return await original_ainvoke(*args, **kwargs)  # type: ignore
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    if not _is_rate_limit(e):
                        raise
                    wait = _parse_retry_after(e)
                    if wait is None:
                        wait = min(delay, 120)
                        delay = min(int(delay * 1.8) + 1, 120)
                    # Async sleep
                    await __import__("asyncio").sleep(max(wait, 1))
                    attempt += 1
            raise last_err
        setattr(llm, "ainvoke", _retry_ainvoke)
    return llm

def get_llm(
    model: str = "claude-3-5-sonnet-20241022",
    temperature: float = 1.0,
    stop_sequences: list[str] | None = None,
    source: SourceType | None = None,
    base_url: str | None = None,
    api_key: str = "EMPTY",
) -> BaseChatModel:
    """
    Get a language model instance based on the specified model name and source.
    This function supports models from OpenAI, Azure OpenAI, Anthropic, Ollama, Gemini, Bedrock, and custom model serving.
    Args:
        model (str): The model name to use
        temperature (float): Temperature setting for generation
        stop_sequences (list): Sequences that will stop generation
        source (str): Source provider: "OpenAI", "AzureOpenAI", "Anthropic", "Ollama", "Gemini", "Bedrock", or "Custom"
                      If None, will attempt to auto-detect from model name
        base_url (str): The base URL for custom model serving (e.g., "http://localhost:8000/v1"), default is None
        api_key (str): The API key for the custom llm
    """
    # Auto-detect source from model name if not specified
    if source is None:
        if model[:7] == "claude-":
            source = "Anthropic"
        elif model.startswith(("gpt-", "gpt/")):
            source = "OpenAI"
        elif model.startswith("azure-"):
            source = "AzureOpenAI"
        elif model[:7] == "gemini-":
            source = "Gemini"
        elif "groq" in model.lower():
            source = "Groq"
        elif base_url is not None:
            source = "Custom"
        elif "/" in model or any(
            name in model.lower()
            for name in [
                "llama",
                "mistral",
                "qwen",
                "gemma",
                "phi",
                "dolphin",
                "orca",
                "vicuna",
                "deepseek",
                "gpt-oss",
            ]
        ):
            source = "Ollama"
        elif model.startswith(
            ("anthropic.claude-", "amazon.titan-", "meta.llama-", "mistral.", "cohere.", "ai21.", "us.")
        ):
            source = "Bedrock"
        else:
            raise ValueError("Unable to determine model source. Please specify 'source' parameter.")

    # Create appropriate model based on source
    # Determine whether to forward stop sequences. Some models (e.g., GPT-5 family) do not support 'stop'.
    disallow_stop = ("gpt-5" in model.lower()) or ("gpt/5" in model.lower())
    if source == "OpenAI":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-openai package is required for OpenAI models. Install with: pip install langchain-openai"
            )
        if disallow_stop:
            llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                max_retries=10,
                timeout=120,
            )
        else:
            llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                stop_sequences=stop_sequences,
                max_retries=10,
                timeout=120,
            )
        return _wrap_llm_with_retry(llm)

    elif source == "AzureOpenAI":
        try:
            from langchain_openai import AzureChatOpenAI
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-openai package is required for Azure OpenAI models. Install with: pip install langchain-openai"
            )
        if ("gpt-5" in model.lower()) or ("gpt/5" in model.lower()):
            API_VERSION = "2025-03-01-preview"
        else:
            API_VERSION = "2024-12-01-preview"
        model = model.replace("azure-", "")
        llm = AzureChatOpenAI(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            azure_endpoint=os.getenv("OPENAI_ENDPOINT"),
            azure_deployment=model,
            openai_api_version=API_VERSION,
            temperature=temperature,
            max_retries=10,
            timeout=120,
        )
        return _wrap_llm_with_retry(llm)

    elif source == "Anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-anthropic package is required for Anthropic models. Install with: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=8192,
            stop_sequences=stop_sequences,
            max_retries=10,
        )

    elif source == "Gemini":
        # If you want to use ChatGoogleGenerativeAI, you need to pass the stop sequences upon invoking the model.
        # return ChatGoogleGenerativeAI(
        #     model=model,
        #     temperature=temperature,
        #     google_api_key=api_key,
        # )
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-openai package is required for Gemini models. Install with: pip install langchain-openai"
            )
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=os.getenv("GEMINI_API_KEY"),
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            stop_sequences=stop_sequences,
            max_retries=10,
            timeout=120,
        )

    elif source == "Groq":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-openai package is required for Groq models. Install with: pip install langchain-openai"
            )
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
            stop_sequences=stop_sequences,
            max_retries=10,
            timeout=120,
        )

    elif source == "Ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-ollama package is required for Ollama models. Install with: pip install langchain-ollama"
            )
        return ChatOllama(
            model=model,
            temperature=temperature,
        )

    elif source == "Bedrock":
        try:
            from langchain_aws import ChatBedrock
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-aws package is required for Bedrock models. Install with: pip install langchain-aws"
            )
        return ChatBedrock(
            model=model,
            temperature=temperature,
            stop_sequences=stop_sequences,
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )

    elif source == "Custom":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(  # noqa: B904
                "langchain-openai package is required for custom models. Install with: pip install langchain-openai"
            )
        # Custom LLM serving such as SGLang. Must expose an openai compatible API.
        assert base_url is not None, "base_url must be provided for customly served LLMs"
        if disallow_stop:
            llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=8192,
                base_url=base_url,
                api_key=api_key,
                max_retries=10,
                timeout=120,
            )
        else:
            llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=8192,
                stop_sequences=stop_sequences,
                base_url=base_url,
                api_key=api_key,
                max_retries=10,
                timeout=120,
            )
        return llm

    else:
        raise ValueError(
            f"Invalid source: {source}. Valid options are 'OpenAI', 'AzureOpenAI', 'Anthropic', 'Gemini', 'Groq', 'Bedrock', or 'Ollama'"
        )
