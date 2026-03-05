from collections.abc import Iterator

from langchain_text_splitters import RecursiveCharacterTextSplitter


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\r", "\n").split())


def chunk_text(text: str, chunk_size: int, overlap: int) -> Iterator[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    normalized = normalize_text(text)
    if not normalized:
        return

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", "。", " ", ""],
        keep_separator=True,
        strip_whitespace=True,
    )
    chunks = splitter.split_text(normalized)
    for chunk in chunks:
        chunk = chunk.strip()
        if chunk:
            yield chunk
