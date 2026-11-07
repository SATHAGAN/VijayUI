import base64
import csv
import io
import json
import os
import secrets

from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import cast, Text

from . import engine as E, parsers
from .analytics import dashboard
from .db import Base, engine as db_engine, get_db
from .models import ImportBatch, Record, ColumnMapping, AuditLog
from .modules import MODULES
from .reports import build_xlsx

Base.metadata.create_all(db_engine)
app = FastAPI(title="OHC Data Hub")
HERE = os.path.dirname(os.path.dirname(__file__))


@app.middleware("http")
async def basic_auth(request, call_next):
    pw = os.getenv("APP_PASSWORD")
    if pw and request.url.path != "/healthz":
        ok, h = False, request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                ok = secrets.compare_digest(base64.b64decode(h[6:]).decode().partition(":")[2], pw)
            except Exception:
                pass
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="OHC Data Hub"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def mod_or_400(m):
    if m not in MODULES:
        raise HTTPException(400, f"Unknown module '{m}'")
    return m


@app.get("/api/modules")
def modules():
    return MODULES


@app.get("/api/locations")
def locations(db=Depends(get_db)):
    return sorted({r[0] for r in db.query(Record.location).distinct()})


# ------------------------------------------------ import pipeline
def batch_out(b, rows=True):
    d = dict(id=b.id, module=b.module, source=b.source, file_name=b.file_name, status=b.status,
             counts=b.counts, missing=b.missing, mapping=b.mapping, headers=b.headers,
             requires_verification=b.requires_verification, created_at=b.created_at.isoformat(),
             committed_at=b.committed_at.isoformat() if b.committed_at else None)
    if rows:
        d["rows"], d["extracted_text"] = b.rows, b.extracted_text
    return d


async def load(file, text, header_row):
    content = await file.read() if file else None
    try:
        return (*parsers.read_input(file.filename if file else None, content, text, header_row), file.filename if file else None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Could not read the input: {e}")


@app.post("/api/import/inspect")
async def inspect(module: str = Form(...), file: UploadFile = File(None), text: str = Form(""),
                  header_row: int = Form(0), mapping_name: str = Form(""), db=Depends(get_db)):
    mod_or_400(module)
    tables, source, extracted, fname = await load(file, text, header_row)
    saved = None
    if mapping_name:
        m = db.query(ColumnMapping).filter_by(module=module, name=mapping_name).first()
        saved = m.mapping if m else None
    sug = {}
    for t in tables:
        sug.update(E.suggest_mapping(module, t["headers"], saved))
    return dict(source=source, file_name=fname, mapping=sug,
                sheets=[dict(name=t["sheet"], headers=t["headers"], rows=len(t["rows"]), sample=t["rows"][:3]) for t in tables])


@app.post("/api/import/stage")
async def stage(module: str = Form(...), file: UploadFile = File(None), text: str = Form(""),
                sheets: str = Form(""), mapping: str = Form("{}"), default_location: str = Form(""),
                default_month: str = Form(""), sheet_as_location: bool = Form(False),
                header_row: int = Form(0), db=Depends(get_db)):
    mod_or_400(module)
    tables, source, extracted, fname = await load(file, text, header_row)
    wanted = [s for s in sheets.split("|") if s]
    if wanted:
        tables = [t for t in tables if t["sheet"] in wanted]
    if not tables:
        raise HTTPException(400, "No data found to import (check sheet selection and header row)")
    rows, missing, eff = E.build_rows(module, tables, json.loads(mapping or "{}"),
                                      {"location": default_location.strip(), "month": default_month.strip()},
                                      sheet_as_location, header_row)
    b = ImportBatch(module=module, source=source, file_name=fname, rows=rows, mapping=eff, missing=missing,
                    headers=sorted({h for t in tables for h in t["headers"]}),
                    requires_verification=(source == "PDF"), extracted_text=extracted)
    db.add(b)
    E.classify(db, b)
    E.audit(db, "batch", b.id, "stage", {"module": module, "source": source, "file": fname, "rows": len(rows)})
    db.commit()
    return batch_out(b)


def get_batch(db, bid):
    b = db.get(ImportBatch, bid)
    if not b:
        raise HTTPException(404, "Import batch not found")
    return b


@app.get("/api/import/{bid}")
def get_import(bid: str, db=Depends(get_db)):
    return batch_out(get_batch(db, bid))


class RowEdit(BaseModel):
    mapped: dict


@app.put("/api/import/{bid}/rows/{idx}")
def edit_row(bid: str, idx: int, body: RowEdit, db=Depends(get_db)):
    b = get_batch(db, bid)
    if b.status in ("committed", "discarded"):
        raise HTTPException(409, "Batch is closed")
    rows = list(b.rows)
    if not 0 <= idx < len(rows) or rows[idx].get("result") in E.DONE:
        raise HTTPException(404, "Row not editable")
    rows[idx] = {**rows[idx], "mapped": {k: v for k, v in body.mapped.items() if v not in (None, "")}}
    b.rows = rows
    E.classify(db, b)
    E.audit(db, "batch", b.id, "row_edit", {"row": idx})
    db.commit()
    return batch_out(b)


class CommitIn(BaseModel):
    default_action: str = "skip"      # skip | update | keep | review
    decisions: dict = {}
    verified: bool = False


@app.post("/api/import/{bid}/commit")
def commit_import(bid: str, body: CommitIn, db=Depends(get_db)):
    b = get_batch(db, bid)
    if b.status in ("committed", "discarded"):
        raise HTTPException(409, f"Batch already {b.status}")
    if b.requires_verification and not body.verified:
        raise HTTPException(400, "PDF-extracted data must be verified by a person before saving")
    if body.default_action not in ("skip", "update", "keep", "review"):
        raise HTTPException(400, "Invalid duplicate action")
    E.classify(db, b)                       # re-check against the database right before saving
    E.commit(db, b, body.default_action, body.decisions)
    db.commit()
    return batch_out(b)


@app.delete("/api/import/{bid}")
def discard(bid: str, db=Depends(get_db)):
    b = get_batch(db, bid)
    if b.status == "committed":
        raise HTTPException(409, "Committed batches cannot be discarded")
    b.status = "discarded"
    E.audit(db, "batch", b.id, "discard")
    db.commit()
    return {"ok": True}


@app.get("/api/import/{bid}/rejected.csv")
def rejected(bid: str, db=Depends(get_db)):
    b = get_batch(db, bid)
    bad = [r for r in b.rows if r["status"] == "invalid" or (r["status"] == "duplicate" and r.get("result") != "updated")]
    cols = list(b.headers)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Sheet", "Row"] + cols + ["Outcome", "Explanation"])
    for r in bad:
        if r["status"] == "invalid":
            why, outcome = "; ".join(r["errors"]), "Rejected"
        else:
            why = {"exact": "Identical record already exists", "conflict": "Conflicts with existing record #%s" % r.get("existing_id"),
                   "in_file": "Duplicate of an earlier row in this file"}.get(r.get("dup_type"), "Duplicate")
            outcome = "Duplicate (%s)" % (r.get("result") or "pending")
        w.writerow([r["sheet"], r["row_number"]] + [r["raw"].get(c) for c in cols] + [outcome, why])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="rejected_{bid[:8]}.csv"'})


@app.get("/api/imports")
def imports(db=Depends(get_db)):
    return [batch_out(b, rows=False) for b in db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(200)]


@app.post("/api/import/api")
def api_import(payload: dict, db=Depends(get_db)):
    """Future REST integrations: {"module": "...", "source_name": "...", "records": [{field: value}, ...]}
    Rows are staged exactly like an upload; a person (or an automated client) then calls /commit."""
    module = mod_or_400(payload.get("module", ""))
    recs = payload.get("records") or []
    rows = [dict(idx=i, sheet="API", row_number=i + 1, raw=r, mapped={k: v for k, v in r.items() if v not in (None, "")})
            for i, r in enumerate(recs)]
    b = ImportBatch(module=module, source="API", file_name=payload.get("source_name"), rows=rows,
                    headers=sorted({k for r in recs for k in r}))
    db.add(b)
    E.classify(db, b)
    E.audit(db, "batch", b.id, "stage", {"module": module, "source": "API", "rows": len(rows)})
    db.commit()
    return batch_out(b)


# ------------------------------------------------ saved mappings
class MappingIn(BaseModel):
    module: str
    name: str
    mapping: dict


@app.get("/api/mappings")
def mappings(module: str, db=Depends(get_db)):
    return [dict(name=m.name, mapping=m.mapping) for m in db.query(ColumnMapping).filter_by(module=module)]


@app.post("/api/mappings")
def save_mapping(body: MappingIn, db=Depends(get_db)):
    mod_or_400(body.module)
    m = db.query(ColumnMapping).filter_by(module=body.module, name=body.name).first()
    clean = {k: v for k, v in body.mapping.items() if v}
    if m:
        m.mapping = clean
    else:
        db.add(ColumnMapping(module=body.module, name=body.name, mapping=clean))
    db.commit()
    return {"ok": True}


# ------------------------------------------------ records (manual entry, edit, delete)
def rec_out(r):
    return dict(id=r.id, module=r.module, location=r.location, reporting_month=r.reporting_month, data=r.data,
                source=r.source, source_file=r.source_file, batch_id=r.batch_id, status=r.status,
                created_at=r.created_at.isoformat(), updated_at=r.updated_at.isoformat())


class RecIn(BaseModel):
    module: str = ""
    data: dict
    status: str = "submitted"
    action: str | None = None         # update | keep (answer to a duplicate prompt)


@app.get("/api/records")
def list_records(module: str = None, month: str = None, location: str = None, status: str = None,
                 source: str = None, q: str = None, limit: int = 500, db=Depends(get_db)):
    qs = db.query(Record)
    for col, val in ((Record.module, module), (Record.reporting_month, month), (Record.location, location),
                     (Record.status, status), (Record.source, source)):
        if val:
            qs = qs.filter(col == val)
    if q:
        qs = qs.filter(cast(Record.data, Text).ilike(f"%{q}%"))
    return [rec_out(r) for r in qs.order_by(Record.updated_at.desc()).limit(min(limit, 2000))]


@app.post("/api/records")
def create_rec(body: RecIn, db=Depends(get_db)):
    mod = mod_or_400(body.module)
    if body.status not in ("draft", "submitted"):
        raise HTTPException(400, "status must be draft or submitted")
    data, errs = E.validate(mod, body.data, draft=body.status == "draft")
    if errs:
        raise HTTPException(422, errs)
    ex = db.query(Record).filter_by(module=mod, natural_key=E.compute_key(mod, data)).first()
    if ex:
        if body.action == "keep":
            return rec_out(ex)
        if body.action != "update":
            raise HTTPException(409, {"message": "A record with the same business key already exists", "existing": rec_out(ex)})
        E.update_record(db, ex, data, "Manual", None, None, body.status)
        db.commit()
        return rec_out(ex)
    r = E.create_record(db, mod, data, body.status, "Manual", None, None)
    db.commit()
    return rec_out(r)


@app.put("/api/records/{rid}")
def edit_rec(rid: int, body: RecIn, db=Depends(get_db)):
    r = db.get(Record, rid)
    if not r:
        raise HTTPException(404, "Record not found")
    data, errs = E.validate(r.module, body.data, draft=body.status == "draft")
    if errs:
        raise HTTPException(422, errs)
    clash = db.query(Record).filter(Record.module == r.module, Record.natural_key == E.compute_key(r.module, data),
                                    Record.id != rid).first()
    if clash:
        raise HTTPException(409, {"message": "Another record already uses this business key", "existing": rec_out(clash)})
    E.update_record(db, r, data, status=body.status)
    db.commit()
    return rec_out(r)


@app.delete("/api/records/{rid}")
def delete_rec(rid: int, db=Depends(get_db)):
    r = db.get(Record, rid)
    if not r:
        raise HTTPException(404, "Record not found")
    E.audit(db, "record", rid, "delete", {"module": r.module, "data": r.data, "source": r.source})
    db.delete(r)
    db.commit()
    return {"ok": True}


# ------------------------------------------------ analytics / reports / audit
@app.get("/api/dashboard")
def dash(month: str, location: str = None, db=Depends(get_db)):
    return dashboard(db, month, location or None)


@app.get("/api/report.xlsx")
def report(month: str, location: str = None, db=Depends(get_db)):
    return Response(build_xlsx(db, month, location or None),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="performance_report_{month}.xlsx"'})


@app.get("/api/audit")
def audit_log(limit: int = 200, db=Depends(get_db)):
    return [dict(ts=a.ts.isoformat(timespec="seconds"), entity=a.entity, entity_id=a.entity_id, action=a.action, detail=a.detail)
            for a in db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))]


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))
