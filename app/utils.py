from collections.abc import Iterator
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter


_OPEN_BRACKETS = "([{\u3010"
_CLOSE_BRACKETS = ")]}\u3011"


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\r", "\n").split())


def clean_source_excerpt(text: str) -> str:
    cleaned = normalize_text(text)
    cleaned = re.sub(r"제\s*(\d+)\s*([장조항호목])", r"제\1\2", cleaned)
    cleaned = re.sub(rf"([{re.escape(_OPEN_BRACKETS)}])\s+", r"\1", cleaned)
    cleaned = re.sub(rf"\s+([{re.escape(_CLOSE_BRACKETS)}])", r"\1", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(rf"([{re.escape(_CLOSE_BRACKETS)}])(?=[0-9A-Za-z\u3131-\u318E\uAC00-\uD7A3])", r"\1 ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def compact_match_text(text: str) -> str:
    compact = clean_source_excerpt(text)
    compact = re.sub(r"\s+", "", compact)
    compact = re.sub(r"[^0-9A-Za-z\u3131-\u318E\uAC00-\uD7A3]", "", compact)
    return compact.lower()


def _normalize_chunk_source_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def chunk_text(text: str, chunk_size: int, overlap: int) -> Iterator[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    normalized = _normalize_chunk_source_text(text)
    if not normalized:
        return

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=[
            "\n제\\s*\\d+\\s*조",
            "\n\n",
            "\n",
            ". ",
            "? ",
            "! ",
            " ",
            "",
        ],
        keep_separator=True,
        strip_whitespace=True,
        is_separator_regex=True,
    )
    chunks = splitter.split_text(normalized)
    for chunk in chunks:
        chunk = chunk.strip()
        if chunk:
            yield chunk
