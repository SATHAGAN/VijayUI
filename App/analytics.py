"""KPI engine. Reads only submitted records; the `source` column is never used in a calculation."""
from collections import Counter
from datetime import date

from .models import Record
from .modules import MODULES


def _top(counter, n=5):
    return dict(counter.most_common(n))


def dashboard(db, month, location=None):
    q = db.query(Record).filter(Record.reporting_month == month)
    if location:
        q = q.filter(Record.location == location)
    allr = q.all()
    recs = [r for r in allr if r.status == "submitted"]
    by = {m: [r.data for r in recs if r.module == m] for m in MODULES}
    k = {}

    a = Counter(d.get("status") for d in by["attendance"])
    work = sum(v for s, v in a.items() if s not in ("Holiday", "Week Off"))
    k["attendance"] = dict(metrics={
        "Records": len(by["attendance"]), "Present": a["Present"], "Absent": a["Absent"], "Leave": a["Leave"],
        "Attendance %": round((a["Present"] + 0.5 * a["Half Day"]) / work * 100, 1) if work else None,
        "Absenteeism %": round(a["Absent"] / work * 100, 1) if work else None})

    hc = sum(d.get("headcount", 0) for d in by["manpower"])
    cat = Counter()
    for d in by["manpower"]:
        cat[d["category"]] += d.get("headcount", 0)
    k["manpower"] = dict(metrics={"Total headcount": hc}, tables={"By category": dict(cat)})

    pv = by["patient_visits"]
    k["patient_visits"] = dict(metrics={
        "Total visits": len(pv), "Unique employees": len({d.get("employee_id") for d in pv}),
        "Visits per 100 employees": round(len(pv) / hc * 100, 1) if hc else None},
        tables={"By visit type": dict(Counter(d.get("visit_type") or "Unspecified" for d in pv))})

    al = Counter()
    for d in by["ailment"]:
        al[d["ailment"]] += d.get("cases", 0)
    k["ailment"] = dict(metrics={"Total cases": sum(al.values()), "Distinct ailments": len(al)},
                        tables={"Top ailments": _top(al)})

    inj = by["injuries"]
    k["injuries"] = dict(metrics={
        "Total injuries": len(inj), "Lost-time injuries": sum(1 for d in inj if d.get("severity") == "Lost Time" or d.get("lost_days", 0) > 0),
        "Lost days": sum(d.get("lost_days", 0) for d in inj)},
        tables={"By severity": dict(Counter(d["severity"] for d in inj))})

    iss = by["issues"]
    closed = sum(1 for d in iss if d.get("status") == "Closed")
    today = date.today().isoformat()
    k["issues"] = dict(metrics={
        "Total issues": len(iss), "Closed": closed, "Open / in progress": len(iss) - closed,
        "Closure %": round(closed / len(iss) * 100, 1) if iss else None,
        "Overdue": sum(1 for d in iss if d.get("status") != "Closed" and d.get("due_date") and d["due_date"] < today)})

    for m, v in k.items():
        v["label"] = MODULES[m]["label"]
        v["records"] = len(by[m])
    sources = {m: dict(Counter(r.source for r in recs if r.module == m)) for m in MODULES}
    return dict(month=month, location=location, kpis=k, sources=sources,
                missing_modules=[MODULES[m]["label"] for m in MODULES if not by[m]],
                drafts_excluded=sum(1 for r in allr if r.status == "draft"))
