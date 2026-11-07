import io
from openpyxl import Workbook
from openpyxl.styles import Font

from .analytics import dashboard
from .models import Record
from .modules import MODULES


def build_xlsx(db, month, location=None):
    d = dashboard(db, month, location)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"Consolidated performance report - {month}" + (f" - {location}" if location else "")])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Draft records are excluded. KPIs are identical regardless of data source."])
    ws.append([])
    for m, v in d["kpis"].items():
        ws.append([v["label"]])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        for name, val in v["metrics"].items():
            ws.append(["", name, val])
        for tname, tv in v.get("tables", {}).items():
            ws.append(["", tname])
            for kk, vv in tv.items():
                ws.append(["", "", kk, vv])
        ws.append(["", "Records by source", ", ".join(f"{s}: {n}" for s, n in d["sources"][m].items()) or "-"])
        ws.append([])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 28
    for m, cfg in MODULES.items():
        sh = wb.create_sheet(cfg["label"][:31])
        names = [f["name"] for f in cfg["fields"]]
        sh.append([f["label"] for f in cfg["fields"]] + ["Source", "Source file", "Batch ID", "Status", "Created", "Last modified"])
        for c in sh[1]:
            c.font = Font(bold=True)
        q = db.query(Record).filter(Record.module == m, Record.reporting_month == month)
        if location:
            q = q.filter(Record.location == location)
        for r in q.order_by(Record.id):
            sh.append([r.data.get(n) for n in names] + [r.source, r.source_file, r.batch_id, r.status,
                                                        r.created_at.isoformat(sep=" ", timespec="seconds"),
                                                        r.updated_at.isoformat(sep=" ", timespec="seconds")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
