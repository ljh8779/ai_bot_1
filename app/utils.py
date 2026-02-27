from collections.abc import Iterator


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

    start = 0
    while start < len(normalized):
        hard_end = min(start + chunk_size, len(normalized))
        end = hard_end

        # Prefer splitting at a whitespace boundary to reduce broken tokens.
        if hard_end < len(normalized):
            split_at = normalized.rfind(" ", start + max(1, chunk_size // 2), hard_end)
            if split_at > start:
                end = split_at

        chunk = normalized[start:end].strip()
        if chunk:
            yield chunk
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)
