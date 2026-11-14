import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from src.config.database import get_db
from src.middlewares.auth import current_user, can_write
from src.models import (
    ReaderRoster, ReadingEvent, IngestionRun, ExperimentBatch, EventLedger,
)
from src.schemas.intake import RosterInput, EventInput
from src.services import intake
from src.services.audit import record
from src.utils.serialization import (
    roster_dict, event_dict, run_dict, batch_dict, ledger_dict,
)

router = APIRouter(prefix='/intake')


def _csv_response(columns, rows, filename):
    out = io.StringIO()
    out.write('\ufeff')
    writer = csv.writer(out)
    writer.writerow([c['label'] for c in columns])
    for row in rows:
        line = []
        for c in columns:
            value = row.get(c['key'], '')
            text = str(value)
            if text.startswith(('=', '+', '-', '@', '\t', '\r')):
                text = "'" + text
            line.append(text)
        writer.writerow(line)
    return StreamingResponse(
        iter([out.getvalue().encode('utf-8')]),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


# ---------------- 名册与事件接入 ----------------
@router.post('/roster', status_code=201)
def create_roster(data: RosterInput, db=Depends(get_db), u=Depends(can_write)):
    run, accepted = intake.upsert_roster(db, data.records, u.email, data.source)
    record(db, u.email, 'roster.ingest', {'run': run.id, 'accepted': accepted})
    db.commit()
    return {'run': run_dict(run), 'accepted': accepted,
            'readers': [roster_dict(r) for r in db.scalars(select(ReaderRoster).order_by(ReaderRoster.id))]}


@router.post('/events', status_code=201)
def create_events(data: EventInput, db=Depends(get_db), u=Depends(can_write)):
    run, accepted, duplicates = intake.ingest_events(db, data.records, u.email, data.source)
    record(db, u.email, 'events.ingest',
           {'run': run.id, 'accepted': accepted, 'duplicates': len(duplicates)})
    db.commit()
    # 同请求内顺带尝试构建已到期窗口的批次（内部按窗口独立提交，可重复调用恢复）
    batches = intake.build_batches(db)
    return {'run': run_dict(run), 'accepted': accepted, 'duplicates': duplicates,
            'batches': [batch_dict(b) for b in batches]}


@router.get('/roster')
def list_roster(db=Depends(get_db), u=Depends(current_user)):
    return [roster_dict(r) for r in db.scalars(select(ReaderRoster).order_by(ReaderRoster.id))]


@router.get('/events')
def list_events(limit: int = 500, db=Depends(get_db), u=Depends(current_user)):
    limit = max(1, min(limit, 5000))
    rows = db.scalars(select(ReadingEvent).order_by(ReadingEvent.receive_no.desc()).limit(limit))
    return [event_dict(e) for e in rows]


@router.get('/runs')
def list_runs(db=Depends(get_db), u=Depends(current_user)):
    return [run_dict(r) for r in db.scalars(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(100))]


# ---------------- 试验批次 ----------------
@router.get('/batches')
def list_batches(db=Depends(get_db), u=Depends(current_user)):
    return [batch_dict(b) for b in db.scalars(
        select(ExperimentBatch).order_by(ExperimentBatch.id.desc()))]


@router.post('/batches/build', status_code=201)
def rebuild(db=Depends(get_db), u=Depends(can_write)):
    batches = intake.build_batches(db)
    record(db, u.email, 'batch.build', {'batches': [b.id for b in batches]})
    db.commit()
    return [batch_dict(b) for b in batches]


@router.get('/batches/{batch_id}')
def batch_detail(batch_id: int, db=Depends(get_db), u=Depends(current_user)):
    b = db.get(ExperimentBatch, batch_id)
    if not b:
        raise HTTPException(404, '试验批次不存在')
    ledger = [ledger_dict(x) for x in db.scalars(
        select(EventLedger).where(EventLedger.batch_id == batch_id).order_by(EventLedger.id))]
    return {**batch_dict(b), 'ledger': ledger}


@router.get('/batches/{batch_id}/ledger')
def batch_ledger(batch_id: int, format: str = 'json', db=Depends(get_db),
                 u=Depends(current_user)):
    b = db.get(ExperimentBatch, batch_id)
    if not b:
        raise HTTPException(404, '试验批次不存在')
    if format not in ('csv', 'json'):
        raise HTTPException(422, '支持 CSV 或 JSON')
    rows = [ledger_dict(x) for x in db.scalars(
        select(EventLedger).where(EventLedger.batch_id == batch_id).order_by(EventLedger.id))]
    columns = [
        {'key': 'event_id', 'label': '事件号'}, {'key': 'reader_id', 'label': '读者'},
        {'key': 'decision', 'label': '纳入/排除'}, {'key': 'reason', 'label': '原因'},
        {'key': 'receive_no', 'label': '接收序号'}, {'key': 'occurred_at', 'label': '发生时间(UTC秒)'}]
    filename = f'batch-{batch_id}-ledger'
    if format == 'csv':
        return _csv_response(columns, rows, filename + '.csv')
    return {'batch': batch_dict(b), 'ledger': rows}
