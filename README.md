# OHC Data Hub – multi-source data ingestion & unified reporting

FastAPI + SQLAlchemy + PostgreSQL, plain-JS UI. Deploys to Render with the included `render.yaml` (Docker, so OCR works).

## Input methods → one engine
Manual form · Excel (.xlsx/.xls, multi-sheet) · CSV · PDF (text/tables/OCR + mandatory human verification) · paste from Excel (also the bulk-entry route) · REST (`POST /api/import/api`).
All go through `app/engine.py`: map columns → validate → duplicate/conflict detection → preview (valid / invalid / duplicate) → correct → confirm → save → audit.

## Duplicates
Natural key per module is defined in `app/modules.py` (`key`), enforced by a DB unique constraint `(module, natural_key)`.
Imports: per-row or default action **skip / update / keep / review later**. Manual entry on an existing key returns 409 and asks. Nothing is overwritten silently; every update stores old+new values in the audit log.

## Provenance
Each record: source, source file, batch ID, created/modified, reporting month, location, status (draft/submitted). Import history + audit trail tab. Analytics use *submitted* records only and never look at `source`.

## Run locally
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload        # uses SQLite ./local.db unless DATABASE_URL is set
pytest -q
```
OCR locally needs `tesseract-ocr` and `poppler-utils` installed (already in the Docker image).

## Deploy on Render
1. Push this repo to GitHub/GitLab.  2. Render → New → Blueprint → select repo (reads `render.yaml`, creates web service + Postgres).
3. Set `APP_PASSWORD` in the dashboard to turn on HTTP Basic auth (leave unset only for private testing).

## Extend
- New module/field/KPI alias: edit `app/modules.py` (+ KPI in `app/analytics.py`). No schema change (records store validated JSON).
- New source (e.g. SAP/HRMS): produce rows and call the same stage → commit pipeline, as `/api/import/api` does.
- Schema changes later: add Alembic (tables are currently created with `create_all`).
