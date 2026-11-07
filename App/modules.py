"""Module registry. To add a module or data field, edit ONLY this file."""


def f(name, label, type="str", required=False, aliases=(), choices=None, synonyms=None):
    return dict(name=name, label=label, type=type, required=required,
                aliases=list(aliases), choices=choices, synonyms=synonyms or {})


LOC = f("location", "Location", "str", True, ["site", "plant", "unit", "facility", "branch", "work location"])
EMP = ["emp id", "emp no", "employee no", "employee code", "staff id", "emp code", "empid", "ecode"]

MODULES = {
    "attendance": dict(
        label="Attendance", period="date", key=["location", "date", "employee_id"],
        fields=[LOC,
                f("date", "Date", "date", True, ["attendance date", "day"]),
                f("employee_id", "Employee ID", "str", True, EMP),
                f("employee_name", "Employee Name", "str", False, ["name", "emp name"]),
                f("status", "Status", "enum", True, ["attendance", "attendance status"],
                  ["Present", "Absent", "Leave", "Half Day", "Holiday", "Week Off"],
                  {"p": "Present", "a": "Absent", "l": "Leave", "hd": "Half Day", "h": "Holiday", "wo": "Week Off"})]),
    "manpower": dict(
        label="Manpower", period="month", key=["location", "month", "category"],
        fields=[LOC,
                f("month", "Month", "month", True, ["reporting month", "period"]),
                f("category", "Category", "str", True, ["designation", "department", "cadre", "staff category"]),
                f("headcount", "Headcount", "int", True, ["manpower", "count", "strength", "no of employees", "employees"])]),
    "patient_visits": dict(
        label="Patient Visits", period="visit_date", key=["location", "visit_date", "employee_id", "complaint"],
        fields=[LOC,
                f("visit_date", "Visit Date", "date", True, ["date", "date of visit"]),
                f("employee_id", "Employee ID", "str", True, EMP + ["patient id"]),
                f("employee_name", "Employee Name", "str", False, ["name", "patient name"]),
                f("visit_type", "Visit Type", "enum", False, ["type", "category"],
                  ["OPD", "First Aid", "Emergency", "Follow-up", "Referral", "Health Check"]),
                f("complaint", "Complaint", "str", False, ["symptoms", "reason", "reason for visit"])]),
    "ailment": dict(
        label="Ailment Analysis", period="month", key=["location", "month", "ailment"],
        fields=[LOC,
                f("month", "Month", "month", True, ["reporting month", "period"]),
                f("ailment", "Ailment", "str", True, ["disease", "diagnosis", "illness", "condition", "ailment name"]),
                f("cases", "Cases", "int", True, ["count", "no of cases", "patients", "number"])]),
    "injuries": dict(
        label="Workplace Injuries", period="incident_date", key=["location", "incident_date", "employee_id", "injury_type"],
        fields=[LOC,
                f("incident_date", "Incident Date", "date", True, ["date", "date of incident", "accident date"]),
                f("employee_id", "Employee ID", "str", False, EMP),
                f("injury_type", "Injury Type", "str", True, ["type of injury", "nature of injury", "injury"]),
                f("severity", "Severity", "enum", True, ["classification", "injury category"],
                  ["First Aid", "Medical Treatment", "Lost Time", "Fatal"]),
                f("lost_days", "Lost Days", "int", False, ["days lost", "lost time days"]),
                f("description", "Description", "str", False, ["details", "remarks"])]),
    "issues": dict(
        label="Issues & Corrective Actions", period="reported_date", key=["location", "reported_date", "issue"],
        fields=[LOC,
                f("reported_date", "Reported Date", "date", True, ["date", "raised on", "date reported"]),
                f("issue", "Issue", "str", True, ["issue description", "observation", "finding", "problem"]),
                f("corrective_action", "Corrective Action", "str", False, ["action", "action taken", "capa"]),
                f("owner", "Owner", "str", False, ["responsible", "assigned to"]),
                f("due_date", "Due Date", "date", False, ["target date", "deadline"]),
                f("status", "Status", "enum", False, ["action status"], ["Open", "In Progress", "Closed"],
                  {"o": "Open", "c": "Closed", "wip": "In Progress", "completed": "Closed"})]),
}


def field_map(module):
    return {x["name"]: x for x in MODULES[module]["fields"]}
