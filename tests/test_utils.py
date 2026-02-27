import pytest

from app.utils import chunk_text


def test_chunk_text_basic():
    text = "a" * 30
    chunks = list(chunk_text(text, chunk_size=10, overlap=2))
    assert chunks == ["aaaaaaaaaa", "aaaaaaaaaa", "aaaaaaaaaa", "aaaaaa"]


def test_chunk_text_invalid_overlap():
    with pytest.raises(ValueError):
        list(chunk_text("hello", chunk_size=5, overlap=5))


def test_chunk_text_prefers_word_boundary():
    text = "alpha beta gamma delta epsilon"
    chunks = list(chunk_text(text, chunk_size=12, overlap=2))
    assert chunks[0] == "alpha beta"
