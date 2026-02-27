import pytest
from pydantic import ValidationError

from app.schemas import IngestTextRequest


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

