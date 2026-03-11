import pytest

from app.config import Settings


def test_embedding_provider_defaults_to_llm_provider():
    settings = Settings(
        llm_provider="google",
        google_api_key="test-key",
    )

    assert settings.normalized_embedding_provider == "google"
    assert settings.active_embedding_model == settings.google_embedding_model


def test_huggingface_embedding_provider_uses_hf_model():
    settings = Settings(
        llm_provider="google",
        embedding_provider="huggingface",
        google_api_key="test-key",
        hf_embedding_model="nlpai-lab/KURE-v1",
        embedding_dimensions=1024,
    )

    assert settings.normalized_embedding_provider == "huggingface"
    assert settings.active_embedding_model == "nlpai-lab/KURE-v1"


def test_invalid_embedding_provider_is_rejected():
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER must be one of"):
        Settings(
            llm_provider="google",
            embedding_provider="invalid",
            google_api_key="test-key",
        )
