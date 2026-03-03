import pytest
from pydantic import ValidationError

from app.schemas import ChatRequest, IngestTextRequest


def test_ingest_text_request_accepts_valid_acl_metadata():
    payload = IngestTextRequest(
        title="Policy",
        source_name="Wiki",
        content="sample",
        metadata={"allowed_departments": ["HR"], "allowed_roles": ["manager"]},
    )
    assert payload.metadata["allowed_departments"] == ["HR"]


def test_ingest_text_request_rejects_invalid_acl_metadata():
    with pytest.raises(ValidationError):
        IngestTextRequest(
            title="Policy",
            source_name="Wiki",
            content="sample",
            metadata={"allowed_departments": "HR"},
        )


def test_chat_request_accepts_history():
    payload = ChatRequest(
        question="우리회사도 하나?",
        user_id="u-1001",
        history=[
            {"role": "user", "text": "스마트팜이 뭐야?"},
            {"role": "assistant", "text": "스마트팜은 농업 자동화 시스템입니다."},
        ],
    )
    assert len(payload.history) == 2
    assert payload.history[0].role == "user"


def test_chat_request_rejects_invalid_history_role():
    with pytest.raises(ValidationError):
        ChatRequest(
            question="테스트",
            user_id="u-1001",
            history=[{"role": "system", "text": "invalid"}],
        )
