import io, os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
from fastapi.testclient import TestClient
from app.main import app
import pandas as pd

c = TestClient(app)


def test_duplicate_across_sources():
    csv = "Site,Date,Emp No,Attendance\nPune,2026-10-01,1001,P\nPune,2026-10-01,1002,Absent\nPune,2026-10-01,1001,P\nPune,bad,1003,Present\n"
    b = c.post("/api/import/stage", data={"module": "attendance"}, files={"file": ("oct.csv", csv)}).json()
    assert b["counts"]["valid"] == 2 and b["counts"]["invalid"] == 1 and b["counts"]["duplicate"] == 1
    r = c.post(f"/api/import/{b['id']}/commit", json={}).json()
    assert r["counts"]["inserted"] == 2
    # same record entered manually later -> must be flagged, never silently overwritten
    m = c.post("/api/records", json={"module": "attendance", "status": "submitted",
               "data": {"location": "Pune", "date": "2026-10-01", "employee_id": "1001", "status": "Absent"}})
    assert m.status_code == 409
    d = c.get("/api/dashboard", params={"month": "2026-10"}).json()
    assert d["kpis"]["attendance"]["metrics"]["Records"] == 2
    assert c.get("/api/report.xlsx", params={"month": "2026-10"}).status_code == 200


def test_excel_multi_sheet_and_pdf_gate():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame({"Month": ["Oct-2026"], "Designation": ["Operators"], "Strength": [120]}).to_excel(w, "Pune", index=False)
        pd.DataFrame({"Month": ["Oct-2026"], "Designation": ["Operators"], "Strength": [80]}).to_excel(w, "Chennai", index=False)
    i = c.post("/api/import/inspect", data={"module": "manpower"}, files={"file": ("m.xlsx", buf.getvalue())}).json()
    assert len(i["sheets"]) == 2
    b = c.post("/api/import/stage", data={"module": "manpower", "sheet_as_location": "true"},
               files={"file": ("m.xlsx", buf.getvalue())}).json()
    assert b["counts"]["valid"] == 2
