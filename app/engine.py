"""The ONE processing engine: map -> validate -> detect duplicates -> preview -> commit.
   Every input method (Excel/CSV/PDF/paste/manual/API) goes through these functions."""
import re
from copy import deepcopy
from datetime import datetime, date, timedelta

from dateutil import parser as dparser
from sqlalchemy.orm.attributes import flag_modified

from .models import Record, AuditLog, now
from .modules import MODULES, field_map

DONE = ("inserted", "updated", "skipped")
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y",
                "%d-%b-%y", "%d %B %Y", "%b %d, %Y", "%d/%m/%y")
MONTH_FORMATS = ("%Y-%m", "%b-%Y", "%B-%Y", "%b %Y", "%B %Y", "%m/%Y", "%b-%y", "%Y/%m", "%b'%y")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# ---------- value parsing ----------
def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < v < 80000:                       # Excel serial number
            return date(1899, 12, 30) + timedelta(days=int(v))
        raise ValueError(f"'{v}' is not a valid date")
    s = str(v).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        return dparser.parse(s, dayfirst=True).date()
    except Exception:
        raise ValueError(f"'{s}' is not a valid date")


def to_month(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m")
    if isinstance(v, str):
        for fmt in MONTH_FORMATS:
            try:
                return datetime.strptime(v.strip(), fmt).strftime("%Y-%m")
            except ValueError:
                pass
    return to_date(v).strftime("%Y-%m")


def parse_value(f, v):
    t = f["type"]
    try:
        if t == "str":
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            return str(v).strip(), None
        if t in ("int", "float"):
            x = float(v) if isinstance(v, (int, float)) else float(str(v).replace(",", ""))
            if x < 0:
                return None, "must be non-negative"
            if t == "int":
                return (int(x), None) if x.is_integer() else (None, "must be a whole number")
            return x, None
        if t == "date":
            return to_date(v).isoformat(), None
        if t == "month":
            return to_month(v), None
        if t == "enum":
            s = str(v).strip().lower()
            for c in f["choices"]:
                if c.lower() == s:
                    return c, None
            if s in f["synonyms"]:
                return f["synonyms"][s], None
            return None, f"'{v}' is not one of: {', '.join(f['choices'])}"
    except (ValueError, OverflowError) as e:
        msg = str(e)
        return None, msg if "not a valid" in msg else f"invalid {t} value '{v}'"
    return None, "unsupported field type"


def validate(module, mapped, draft=False):
    cfg = MODULES[module]
    data, errs = {}, []
    for f in cfg["fields"]:
        v = mapped.get(f["name"])
        if v is None or (isinstance(v, str) and not v.strip()):
            if f["required"] and not (draft and f["name"] not in cfg["key"]):
                errs.append(f"{f['label']} is required")
            continue
        val, err = parse_value(f, v)
        if err:
            errs.append(f"{f['label']}: {err}")
        else:
            data[f["name"]] = val
    return data, errs


def compute_key(module, data):
    return "|".join(str(data.get(k, "")).strip().lower() for k in MODULES[module]["key"])


def reporting_month(module, data):
    return str(data[MODULES[module]["period"]])[:7]


# ---------- mapping ----------
def suggest_mapping(module, headers, saved=None):
    idx = {}
    for f in MODULES[module]["fields"]:
        for n in [f["name"], f["label"]] + f["aliases"]:
            idx.setdefault(norm(n), f["name"])
    out, used = {}, set()
    for h in headers:
        fld = (saved or {}).get(h) or idx.get(norm(h))
        if fld in used or fld not in field_map(module):
            fld = None
        if fld:
            used.add(fld)
        out[h] = fld
    return out


# ---------- staging ----------
def build_rows(module, tables, mapping, defaults, sheet_as_location=False, header_row=0):
    cfg, fm = MODULES[module], field_map(module)
    period_is_month = fm[cfg["period"]]["type"] == "month"
    rows, missing, eff = [], {}, {}
    for t in tables:
        m = suggest_mapping(module, t["headers"], mapping)
        eff.update({h: v for h, v in m.items()})
        cols = {v for v in m.values() if v}
        miss = []
        for f in cfg["fields"]:
            if not f["required"] or f["name"] in cols:
                continue
            if f["name"] == "location" and (defaults.get("location") or sheet_as_location):
                continue
            if f["name"] == cfg["period"] and period_is_month and defaults.get("month"):
                continue
            miss.append(f["label"])
        if miss:
            missing[t["sheet"]] = miss
        for i, r in enumerate(t["rows"]):
            raw = {h: (r[j] if j < len(r) else None) for j, h in enumerate(t["headers"])}
            mapped = {}
            for h, v in raw.items():
                if m.get(h) and v is not None and m[h] not in mapped:
                    mapped[m[h]] = v
            if not mapped.get("location"):
                loc = t["sheet"] if sheet_as_location else defaults.get("location")
                if loc:
                    mapped["location"] = loc
            if period_is_month and not mapped.get(cfg["period"]) and defaults.get("month"):
                mapped[cfg["period"]] = defaults["month"]
            rows.append(dict(idx=len(rows), sheet=t["sheet"], row_number=i + header_row + 2, raw=raw, mapped=mapped))
    for i, r in enumerate(rows):
        r["idx"] = i
    return rows, missing, eff


def find_existing(db, module, keys):
    keys, out = list({k for k in keys if k}), {}
    for i in range(0, len(keys), 500):
        for r in db.query(Record).filter(Record.module == module, Record.natural_key.in_(keys[i:i + 500])):
            out[r.natural_key] = r
    return out


def summarize(rows):
    c = dict(total=len(rows), valid=0, invalid=0, duplicate=0, inserted=0, updated=0, skipped=0, pending=0)
    for r in rows:
        res = r.get("result")
        if res in DONE:
            c[res] += 1
        else:
            c[r.get("status", "invalid")] += 1
            if r.get("status") == "duplicate":
                c["pending"] += 1
    return c


def classify(db, batch):
    """(Re)validate every open row and mark it valid / invalid / duplicate."""
    rows = deepcopy(batch.rows)
    open_rows = [r for r in rows if r.get("result") not in DONE]
    for r in open_rows:
        r["data"], r["errors"] = validate(batch.module, r["mapped"])
        r["key"] = None if r["errors"] else compute_key(batch.module, r["data"])
        r["dup_type"] = r["existing_id"] = r["existing_data"] = None
    ex = find_existing(db, batch.module, [r["key"] for r in open_rows])
    seen = set()
    for r in open_rows:
        if r["errors"]:
            r["status"] = "invalid"
        elif r["key"] in ex:
            e = ex[r["key"]]
            r.update(status="duplicate", dup_type="exact" if e.data == r["data"] else "conflict",
                     existing_id=e.id, existing_data=e.data)
        elif r["key"] in seen:
            r.update(status="duplicate", dup_type="in_file")
        else:
            r["status"] = "valid"
            seen.add(r["key"])
    batch.rows = rows
    flag_modified(batch, "rows")
    batch.counts = summarize(rows)


# ---------- persistence ----------
def audit(db, entity, entity_id, action, detail=None):
    db.add(AuditLog(entity=entity, entity_id=str(entity_id), action=action, detail=detail or {}))


def create_record(db, module, data, status, source, source_file, batch_id):
    r = Record(module=module, natural_key=compute_key(module, data), location=data["location"],
               reporting_month=reporting_month(module, data), data=data, status=status,
               source=source, source_file=source_file, batch_id=batch_id)
    db.add(r)
    db.flush()
    audit(db, "record", r.id, "create", {"module": module, "source": source, "batch_id": batch_id})
    return r


def update_record(db, rec, data, source=None, source_file=None, batch_id=None, status="submitted"):
    old = rec.data
    rec.data, rec.natural_key = data, compute_key(rec.module, data)
    rec.location, rec.reporting_month, rec.status = data["location"], reporting_month(rec.module, data), status
    flag_modified(rec, "data")
    if source:
        rec.source, rec.source_file, rec.batch_id = source, source_file, batch_id
    rec.updated_at = now()
    db.flush()
    audit(db, "record", rec.id, "update", {"old": old, "new": data, "via": source or "edit"})


def commit(db, batch, default_action, decisions):
    for r in batch.rows:
        if r.get("result") in DONE or r["status"] == "invalid":
            continue
        ex = find_existing(db, batch.module, [r["key"]]).get(r["key"])
        if r["status"] == "valid" and not ex:
            create_record(db, batch.module, r["data"], "submitted", batch.source, batch.file_name, batch.id)
            r["result"] = "inserted"
            continue
        act = "skip" if r["status"] == "valid" else decisions.get(str(r["idx"]), default_action)
        if act == "review":
            continue                                   # stays pending for manual review
        if act == "update" and ex:
            update_record(db, ex, r["data"], batch.source, batch.file_name, batch.id)
            r["result"] = "updated"
        else:                                          # skip / keep existing
            r["result"] = "skipped"
    flag_modified(batch, "rows")
    batch.counts = summarize(batch.rows)
    batch.status = "partial" if batch.counts["pending"] else "committed"
    batch.committed_at = now()
    audit(db, "batch", batch.id, "commit", batch.counts)
