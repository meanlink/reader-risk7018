from sqlalchemy import String, Double, JSON, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class ReaderRoster(Base):
    """读者名册：reader_id 唯一，携带到期日（UTC YYYY-MM-DD）与可选的续读标签。"""
    __tablename__ = 'reader_roster'
    id: Mapped[int] = mapped_column(primary_key=True)
    reader_id: Mapped[str] = mapped_column(String(80), unique=True)
    expire_date: Mapped[str] = mapped_column(String(10))
    renewed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_receive_no: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ReadingEvent(Base):
    """原始阅读事件，事件号全局唯一；同号异内容在接入阶段整批拒绝。"""
    __tablename__ = 'reading_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), unique=True)
    reader_id: Mapped[str] = mapped_column(String(80), index=True)
    session_id: Mapped[str] = mapped_column(String(120))
    issue_no: Mapped[str] = mapped_column(String(60))
    occurred_at: Mapped[float] = mapped_column(Double)
    completion_pct: Mapped[float] = mapped_column(Double)
    payload_checksum: Mapped[str] = mapped_column(String(64))
    receive_no: Mapped[int] = mapped_column(Integer, index=True)
    ingestion_run_id: Mapped[int] = mapped_column(Integer, index=True)
    received_at: Mapped[float] = mapped_column(Double)


class IngestionRun(Base):
    """每次接入（名册或事件）的接收批次记录，记录截至序号与指纹，供批次固定截止点引用。"""
    __tablename__ = 'ingestion_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    offered: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    last_receive_no: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[float] = mapped_column(Double)


class ExperimentBatch(Base):
    """按读者到期前14日窗口生成的试验批次；building 中断可恢复，ready 后不可变。"""
    __tablename__ = 'experiment_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    window_end: Mapped[str] = mapped_column(String(10), index=True)
    window_start: Mapped[str] = mapped_column(String(10))
    # 固定截至的接入接收序号：receive_no 大于该值的迟到记录不进入本批
    cutoff_receive_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='building', index=True)
    dataset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    included_readers: Mapped[int] = mapped_column(Integer, default=0)
    included_events: Mapped[int] = mapped_column(Integer, default=0)
    excluded_events: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class EventLedger(Base):
    """事件纳入/排除台账：每个批次对每个事件至多一行，可追溯原事件号与原因。"""
    __tablename__ = 'event_ledger'
    __table_args__ = (Index('ux_ledger_batch_event', 'batch_id', 'event_id', unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(Integer, index=True)
    event_id: Mapped[str] = mapped_column(String(120))
    reader_id: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(200), default='')
    receive_no: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
