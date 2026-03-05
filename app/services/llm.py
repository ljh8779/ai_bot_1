from functools import lru_cache
import re
from time import sleep

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings

settings = get_settings()
GOOGLE_PROVIDER = "google"
OLLAMA_PROVIDER = "ollama"


@lru_cache
def _get_ollama_client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.ollama_base_url.rstrip("/"),
        timeout=settings.llm_timeout_seconds,
    )


@lru_cache
def _get_google_client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.google_base_url.rstrip("/"),
        timeout=settings.llm_timeout_seconds,
    )


@lru_cache
def _get_chat_model():
    provider = _provider()
    if provider == GOOGLE_PROVIDER:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.google_chat_model,
            google_api_key=_google_api_key(),
            temperature=settings.llm_chat_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url.rstrip("/"),
        temperature=settings.llm_chat_temperature,
        timeout=settings.llm_timeout_seconds,
        num_retries=settings.llm_max_retries,
    )


@lru_cache
def _get_embeddings_model():
    provider = _provider()
    if provider == GOOGLE_PROVIDER:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=settings.google_embedding_model,
            google_api_key=_google_api_key(),
            task_type="RETRIEVAL_DOCUMENT",
        )

    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(
        model=settings.ollama_embedding_model,
        base_url=settings.ollama_base_url.rstrip("/"),
    )


@lru_cache
def _get_query_embeddings_model():
    """Query용 임베딩 모델 (Google은 task_type이 다름)."""
    provider = _provider()
    if provider == GOOGLE_PROVIDER:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=settings.google_embedding_model,
            google_api_key=_google_api_key(),
            task_type="RETRIEVAL_QUERY",
        )

    # Ollama는 query/document 구분 없음
    return _get_embeddings_model()


def _with_retries(request_fn, provider: str):
    max_attempts = settings.llm_max_retries + 1
    last_exc: Exception | None = None
    last_error_message = ""
    for attempt in range(1, max_attempts + 1):
        try:
            return request_fn()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            last_error_message = _format_http_status_error(exc, provider)
            if _is_retryable_status(exc.response.status_code) and attempt < max_attempts:
                sleep(min(0.4 * attempt, 1.2))
                continue
            break
        except httpx.HTTPError as exc:
            last_exc = exc
            last_error_message = str(exc)
            if attempt < max_attempts:
                sleep(min(0.4 * attempt, 1.2))
    provider_name = provider.capitalize()
    raise RuntimeError(f"{provider_name} request failed after {max_attempts} attempts: {last_error_message}") from last_exc


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _provider() -> str:
    return settings.normalized_llm_provider


def _google_api_key() -> str:
    api_key = (settings.google_api_key or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is required when LLM_PROVIDER=google.")
    return api_key


def _extract_error_detail(exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    detail = ""
    try:
        payload = exc.response.json()
        if isinstance(payload, dict):
            if isinstance(payload.get("error"), dict):
                detail = str(payload["error"].get("message") or payload["error"].get("status") or "")
            if not detail:
                detail = str(payload.get("error") or payload.get("detail") or payload.get("message") or "")
    except ValueError:
        detail = exc.response.text.strip()

    if not detail:
        detail = str(exc)
    return f"{status_code}: {detail}"


def _format_http_status_error(exc: httpx.HTTPStatusError, provider: str) -> str:
    status_code = exc.response.status_code
    detail_with_status = _extract_error_detail(exc)
    detail = detail_with_status.split(": ", maxsplit=1)[-1]

    if provider == OLLAMA_PROVIDER:
        model_match = re.search(r'model "([^"]+)" not found', detail)
        if model_match:
            model_name = model_match.group(1)
            return (
                f"Ollama model '{model_name}' is not installed. "
                f"Run: docker exec rag_ollama ollama pull {model_name}"
            )
        return f"Ollama API error ({status_code}): {detail}"

    return f"Google API error ({status_code}): {detail}"


def ping_llm() -> bool:
    provider = _provider()

    if provider == OLLAMA_PROVIDER:
        client = _get_ollama_client()

        def _call():
            response = client.get("/api/tags", timeout=min(settings.llm_timeout_seconds, 5.0))
            response.raise_for_status()
            return True

        try:
            return _with_retries(_call, provider)
        except RuntimeError:
            return False

    if provider == GOOGLE_PROVIDER:
        client = _get_google_client()
        api_key = _google_api_key()

        def _call():
            response = client.get(
                "/v1beta/models",
                params={"key": api_key},
                timeout=min(settings.llm_timeout_seconds, 5.0),
            )
            response.raise_for_status()
            return True

        try:
            return _with_retries(_call, provider)
        except RuntimeError:
            return False

    return False


def get_available_models() -> set[str]:
    provider = _provider()

    if provider == OLLAMA_PROVIDER:
        client = _get_ollama_client()

        def _call() -> set[str]:
            response = client.get("/api/tags", timeout=min(settings.llm_timeout_seconds, 5.0))
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models", [])
            return {str(item.get("name")) for item in models if isinstance(item, dict) and item.get("name")}

        return _with_retries(_call, provider)

    if provider == GOOGLE_PROVIDER:
        client = _get_google_client()
        api_key = _google_api_key()

        def _call() -> set[str]:
            response = client.get(
                "/v1beta/models",
                params={"key": api_key},
                timeout=min(settings.llm_timeout_seconds, 5.0),
            )
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models", [])
            names: set[str] = set()
            for item in models:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                names.add(name)
                if name.startswith("models/"):
                    names.add(name[len("models/") :])
            return names

        return _with_retries(_call, provider)

    raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")


def get_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_embeddings_model()
    return model.embed_documents(texts)


def get_embedding(text: str) -> list[float]:
    model = _get_query_embeddings_model()
    return model.embed_query(text)


def generate_answer(system_prompt: str, user_prompt: str) -> str:
    chat = _get_chat_model()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    response = chat.invoke(messages)
    content = response.content
    if isinstance(content, list):
        content = "".join(str(part) for part in content)
    content = content.strip()
    if not content:
        raise RuntimeError(f"{_provider().capitalize()} chat returned an empty response.")
    return content
