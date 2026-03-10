import pytest

from app.utils import chunk_text, clean_source_excerpt, compact_match_text


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


def test_chunk_text_preserves_article_boundaries():
    text = (
        "\uC81C 1 \uC870 \uD734\uAC00 \uADDC\uC815 \uC548\uB0B4\uC785\uB2C8\uB2E4.\n"
        "\uC81C 2 \uC870 \uACBD\uC870\uC0AC \uADDC\uC815 \uC548\uB0B4\uC785\uB2C8\uB2E4."
    )
    chunks = list(chunk_text(text, chunk_size=20, overlap=0))
    assert len(chunks) == 2
    assert chunks[0].startswith("\uC81C 1 \uC870")
    assert chunks[1].startswith("\uC81C 2 \uC870")


def test_clean_source_excerpt_flattens_pdf_spacing():
    text = "제53\n \n조【 \n \n교육 】 \n \n회사는 \n \n필요한 \n \n교육훈 \n \n련 \n \n계획에 \n \n의하여 \n \n회사"
    assert clean_source_excerpt(text) == "제53조【교육】 회사는 필요한 교육훈 련 계획에 의하여 회사"


def test_compact_match_text_collapses_pdf_artifacts():
    text = "③\n \n경 \n \n조 \n \n휴 \n \n가\n 1.\n \n부모\n \n또는\n \n배우자의\n \n상"
    assert compact_match_text(text) == "③경조휴가1부모또는배우자의상"
