import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FranchisePage
from app.schemas import FranchiseSyncItem, FranchiseSyncResponse
from app.services.notion import collect_target_pages, extract_page_payload

logger = logging.getLogger(__name__)


def _content_hash(*, title: str, content_text: str, properties: dict[str, Any], notion_url: str | None) -> str:
    serialized = json.dumps(
        {
            "title": title,
            "content_text": content_text,
            "properties": properties,
            "notion_url": notion_url,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def sync_franchise_pages(db: Session) -> FranchiseSyncResponse:
    pages_to_sync = collect_target_pages()

    inserted = 0
    updated = 0
    unchanged = 0
    skipped = 0
    failed = 0
    details: list[FranchiseSyncItem] = []

    for page_id, root_id, root_title in pages_to_sync:
        try:
            payload = extract_page_payload(page_id)
            if not payload:
                skipped += 1
                details.append(
                    FranchiseSyncItem(
                        notion_page_id=page_id,
                        title=root_title,
                        status="skipped",
                        message="Notion API fetch failed.",
                    )
                )
                continue

            title = payload["title"].strip() or "Untitled"
            content_text = payload["content_text"]
            properties = payload["properties"]
            notion_url = payload["url"]
            last_edited_time = payload["last_edited_time"]
            content_hash = _content_hash(
                title=title,
                content_text=content_text,
                properties=properties,
                notion_url=notion_url,
            )
            source_name = f"notion/{title}"
            synced_at = datetime.now(timezone.utc)

            existing = db.scalar(select(FranchisePage).where(FranchisePage.notion_page_id == page_id).limit(1))
            if existing:
                if existing.content_hash == content_hash and existing.last_edited_time == last_edited_time:
                    existing.synced_at = synced_at
                    db.commit()
                    unchanged += 1
                    details.append(
                        FranchiseSyncItem(
                            notion_page_id=page_id,
                            title=title,
                            status="unchanged",
                            record_id=existing.id,
                        )
                    )
                    continue

                existing.notion_root_id = root_id
                existing.notion_root_title = root_title[:255]
                existing.title = title[:255]
                existing.source_name = source_name[:255]
                existing.notion_url = notion_url
                existing.last_edited_time = last_edited_time
                existing.content_hash = content_hash
                existing.content_text = content_text
                existing.properties_json = properties
                existing.synced_at = synced_at
                db.commit()
                updated += 1
                details.append(
                    FranchiseSyncItem(
                        notion_page_id=page_id,
                        title=title,
                        status="updated",
                        record_id=existing.id,
                    )
                )
                continue

            record = FranchisePage(
                notion_page_id=page_id,
                notion_root_id=root_id,
                notion_root_title=root_title[:255],
                title=title[:255],
                source_name=source_name[:255],
                notion_url=notion_url,
                last_edited_time=last_edited_time,
                content_hash=content_hash,
                content_text=content_text,
                properties_json=properties,
                synced_at=synced_at,
            )
            db.add(record)
            db.commit()
            inserted += 1
            details.append(
                FranchiseSyncItem(
                    notion_page_id=page_id,
                    title=title,
                    status="inserted",
                    record_id=record.id,
                )
            )
        except Exception as exc:
            db.rollback()
            failed += 1
            logger.exception("Franchise Notion sync failed. page_id=%s", page_id)
            details.append(
                FranchiseSyncItem(
                    notion_page_id=page_id,
                    title=root_title,
                    status="failed",
                    message=str(exc),
                )
            )

    synced = inserted + updated + unchanged
    return FranchiseSyncResponse(
        total_pages=len(pages_to_sync),
        synced=synced,
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        skipped=skipped,
        failed=failed,
        details=details,
    )
