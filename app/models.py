import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON, Text, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.utcnow()


class ImportBatch(Base):
    """One upload/paste/API call. Staged rows live here until the user confirms."""
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    module: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20))          # Excel / CSV / PDF / Paste / API
    file_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="staged")  # staged/committed/partial/discarded
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    rows: Mapped[list] = mapped_column(JSON, default=list)
    headers: Mapped[list] = mapped_column(JSON, default=list)
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    missing: Mapped[dict] = mapped_column(JSON, default=dict)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Record(Base):
    """Single table for every module: analytics never cares where a record came from."""
    __tablename__ = "records"
    __table_args__ = (UniqueConstraint("module", "natural_key", name="uq_module_key"),
                      Index("ix_rec_month", "module", "reporting_month", "location"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module: Mapped[str] = mapped_column(String(40))
    natural_key: Mapped[str] = mapped_column(String(400))
    location: Mapped[str] = mapped_column(String(120))
    reporting_month: Mapped[str] = mapped_column(String(7))
    data: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20))
    source_file: Mapped[str | None] = mapped_column(String(300), nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="submitted")  # draft / submitted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ColumnMapping(Base):
    __tablename__ = "column_mappings"
    __table_args__ = (UniqueConstraint("module", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    mapping: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
