from functools import lru_cache
import re
from time import sleep

import httpx

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


def _google_embed_text(text: str, task_type: str) -> list[float]:
    client = _get_google_client()
    api_key = _google_api_key()

    def _call() -> list[float]:
        response = client.post(
            f"/v1beta/models/{settings.google_embedding_model}:embedContent",
            params={"key": api_key},
            json={
                "model": f"models/{settings.google_embedding_model}",
                "content": {"parts": [{"text": text}]},
                "taskType": task_type,
                "outputDimensionality": settings.embedding_dimensions,
            },
        )
        response.raise_for_status()
        payload = response.json()
        values = payload.get("embedding", {}).get("values", [])
        if not isinstance(values, list) or not values:
            raise RuntimeError("Google embedding API returned an empty vector.")
        return [float(value) for value in values]

    return _with_retries(_call, GOOGLE_PROVIDER)


def get_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    provider = _provider()
    if provider == GOOGLE_PROVIDER:
        return [_google_embed_text(text, "RETRIEVAL_DOCUMENT") for text in texts]

    if provider != OLLAMA_PROVIDER:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")

    client = _get_ollama_client()
    vectors: list[list[float]] = []
    batch_size = settings.ingest_embedding_batch_size

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]

        def _call():
            response = client.post(
                "/api/embed",
                json={
                    "model": settings.ollama_embedding_model,
                    "input": batch,
                },
            )
            response.raise_for_status()
            payload = response.json()
            embeddings = payload.get("embeddings", [])
            if len(embeddings) != len(batch):
                raise RuntimeError("Ollama embeddings length mismatch.")
            return embeddings

        vectors.extend(_with_retries(_call, provider))

    return vectors


def get_embedding(text: str) -> list[float]:
    provider = _provider()
    if provider == GOOGLE_PROVIDER:
        return _google_embed_text(text, "RETRIEVAL_QUERY")
    vectors = get_embeddings([text])
    return vectors[0]


def generate_answer(system_prompt: str, user_prompt: str) -> str:
    provider = _provider()
    if provider == GOOGLE_PROVIDER:
        client = _get_google_client()
        api_key = _google_api_key()

        def _call():
            response = client.post(
                f"/v1beta/models/{settings.google_chat_model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "generationConfig": {"temperature": settings.llm_chat_temperature},
                },
            )
            response.raise_for_status()
            payload = response.json()
            for candidate in payload.get("candidates", []):
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
                if text:
                    return text
            block_reason = payload.get("promptFeedback", {}).get("blockReason")
            if block_reason:
                raise RuntimeError(f"Google response was blocked: {block_reason}")
            raise RuntimeError("Google chat returned an empty response.")

        return _with_retries(_call, provider)

    if provider != OLLAMA_PROVIDER:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")

    client = _get_ollama_client()

    def _call():
        response = client.post(
            "/api/chat",
            json={
                "model": settings.ollama_chat_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {"temperature": settings.llm_chat_temperature},
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("Ollama chat returned an empty response.")
        return content

    return _with_retries(_call, provider)
