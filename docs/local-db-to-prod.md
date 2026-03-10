# Local DB To Prod

This flow is for the case where local ingestion is already complete and you want
to move the local PostgreSQL data into production without re-uploading files.

## Important

- Do not point production at the local machine DB.
- Move the local DB contents into the production DB instead.
- `EMBEDDING_DIMENSIONS` in `.env.prod` must match the local dump metadata.

## 1. Export Local DB

Run on the Windows development machine:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\export_local_db.ps1
```

This creates:

- `tmp\db_migration\*.dump`
- `tmp\db_migration\*.metadata.env`

## 2. Copy Dump To Production Server

Example:

```bash
scp tmp/db_migration/local-rag-db-YYYYMMDD-HHMMSS.dump user@server:/home/user/
scp tmp/db_migration/local-rag-db-YYYYMMDD-HHMMSS.metadata.env user@server:/home/user/
```

## 3. Restore On Production Server

Run from the repository root on the production server:

```bash
bash scripts/restore_prod_db.sh /home/user/local-rag-db-YYYYMMDD-HHMMSS.dump /home/user/local-rag-db-YYYYMMDD-HHMMSS.metadata.env
```

The restore script:

- backs up the current production DB first
- stops `api`
- restores the local dump
- starts `api`
- runs a health check

## 4. If Restore Fails On Embedding Dimensions

The dump metadata file contains `EXPECTED_EMBEDDING_DIMENSIONS`.
Update `.env.prod` to the same value and rerun the restore.
