from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas import BulkIngestItem, BulkIngestResponse
from app.services.file_extract import SUPPORTED_UPLOAD_SUFFIXES, extract_content_from_upload
from app.services.rag import ingest_text_document

settings = get_settings()
ZIP_SUFFIX = ".zip"


def _trim_title(raw_title: str) -> str:
    title = (raw_title or "").strip()
    if not title:
        return "untitled"
    return title[:255]


def _file_size_limit_bytes() -> int:
    return settings.max_upload_size_mb * 1024 * 1024


def _ingest_raw_content(
    db: Session,
    *,
    title: str,
    source_name: str,
    source_type: str,
    suffix: str,
    raw: bytes,
    metadata: dict,
) -> tuple[str, int]:
    content = extract_content_from_upload(suffix, raw)
    return ingest_text_document(
        db,
        title=title,
        source_type=source_type,
        source_name=source_name,
        content=content,
        metadata=metadata,
    )


def _append_detail(
    details: list[BulkIngestItem],
    item: BulkIngestItem,
) -> None:
    if len(details) < settings.bulk_ingest_details_limit:
        details.append(item)


def ingest_directory(db: Session, *, root_dir: Path) -> BulkIngestResponse:
    root_dir = root_dir.expanduser()
    if not root_dir.exists():
        raise FileNotFoundError(f"Directory not found: {root_dir}")
    if not root_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {root_dir}")

    max_files = settings.bulk_ingest_max_files
    max_zip_members = settings.bulk_ingest_zip_member_limit
    max_upload_bytes = _file_size_limit_bytes()

    scanned_files = 0
    ingested_files = 0
    skipped_files = 0
    failed_files = 0
    total_chunks = 0
    details: list[BulkIngestItem] = []

    def hit_limit() -> bool:
        return scanned_files >= max_files

    for path in root_dir.rglob("*"):
        if hit_limit():
            break
        if not path.is_file():
            continue

        suffix = path.suffix.lower()
        if suffix == ZIP_SUFFIX:
            try:
                with ZipFile(path, "r") as archive:
                    member_count = 0
                    for member in archive.infolist():
                        if hit_limit():
                            break
                        if member.is_dir():
                            continue
                        member_count += 1
                        if member_count > max_zip_members:
                            _append_detail(
                                details,
                                BulkIngestItem(
                                    source_path=f"{path}::{member.filename}",
                                    status="skipped",
                                    message=f"ZIP member limit exceeded ({max_zip_members}).",
                                ),
                            )
                            skipped_files += 1
                            break

                        member_suffix = Path(member.filename).suffix.lower()
                        if member_suffix not in SUPPORTED_UPLOAD_SUFFIXES:
                            continue

                        scanned_files += 1
                        source_path = f"{path}::{member.filename}"
                        if member.file_size > max_upload_bytes:
                            failed_files += 1
                            _append_detail(
                                details,
                                BulkIngestItem(
                                    source_path=source_path,
                                    status="failed",
                                    message=f"File too large (>{settings.max_upload_size_mb} MB).",
                                ),
                            )
                            continue

                        try:
                            raw = archive.read(member)
                            rel = PurePosixPath(member.filename)
                            document_id, chunk_count = _ingest_raw_content(
                                db,
                                title=_trim_title(rel.stem),
                                source_name=f"bulk-zip:{path.name}",
                                source_type="bulk-zip",
                                suffix=member_suffix,
                                raw=raw,
                                metadata={
                                    "ingest_mode": "bulk-directory",
                                    "archive_path": str(path),
                                    "archive_member": member.filename,
                                },
                            )
                            ingested_files += 1
                            total_chunks += chunk_count
                            _append_detail(
                                details,
                                BulkIngestItem(
                                    source_path=source_path,
                                    status="ingested",
                                    document_id=document_id,
                                    chunk_count=chunk_count,
                                ),
                            )
                        except Exception as exc:
                            failed_files += 1
                            _append_detail(
                                details,
                                BulkIngestItem(
                                    source_path=source_path,
                                    status="failed",
                                    message=str(exc),
                                ),
                            )
            except (BadZipFile, OSError) as exc:
                failed_files += 1
                _append_detail(
                    details,
                    BulkIngestItem(
                        source_path=str(path),
                        status="failed",
                        message=f"Invalid ZIP: {exc}",
                    ),
                )
            continue

        if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
            continue

        scanned_files += 1
        if path.stat().st_size > max_upload_bytes:
            failed_files += 1
            _append_detail(
                details,
                BulkIngestItem(
                    source_path=str(path),
                    status="failed",
                    message=f"File too large (>{settings.max_upload_size_mb} MB).",
                ),
            )
            continue

        try:
            raw = path.read_bytes()
            rel_path = path.relative_to(root_dir)
            document_id, chunk_count = _ingest_raw_content(
                db,
                title=_trim_title(path.stem),
                source_name="bulk-directory",
                source_type="bulk-file",
                suffix=suffix,
                raw=raw,
                metadata={
                    "ingest_mode": "bulk-directory",
                    "relative_path": str(rel_path),
                },
            )
            ingested_files += 1
            total_chunks += chunk_count
            _append_detail(
                details,
                BulkIngestItem(
                    source_path=str(path),
                    status="ingested",
                    document_id=document_id,
                    chunk_count=chunk_count,
                ),
            )
        except Exception as exc:
            failed_files += 1
            _append_detail(
                details,
                BulkIngestItem(
                    source_path=str(path),
                    status="failed",
                    message=str(exc),
                ),
            )

    if hit_limit():
        skipped_files += 1
        _append_detail(
            details,
            BulkIngestItem(
                source_path=str(root_dir),
                status="skipped",
                message=f"File scan limit reached ({max_files}). Increase BULK_INGEST_MAX_FILES if needed.",
            ),
        )

    return BulkIngestResponse(
        root_directory=str(root_dir),
        scanned_files=scanned_files,
        ingested_files=ingested_files,
        skipped_files=skipped_files,
        failed_files=failed_files,
        total_chunks=total_chunks,
        details=details,
    )
