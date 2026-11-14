"""阅读事件分批接入与试验批次构建。

口径（与 BUSINESS.md 对齐）：
- 试验窗口：读者到期日（UTC）前 14 日（含）到到期日前一日，共 14 个自然日。
- 访问按会话去重；完成率按各期末次记录取平均；未读天数按末次访问；已读期数按期号去重。
- 重复事件号不多计；同号异内容整批拒绝（接入侧原子事务）。
- 每份试验批次固定截至接入接收序号 cutoff_receive_no；迟到记录不回写已就绪批次，
  同窗口在截止点后收到成员新事件时新建更高截止点的版本批次（旧批次不可变）。
- 构建按窗口分组逐组提交，中断后重入先清理半成品台账再重建；未写齐的 building 批次不供试验使用。
"""
import time
import math
import json
import hashlib
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, func

from src.models import (
    ReaderRoster, ReadingEvent, IngestionRun, ExperimentBatch, EventLedger, Dataset,
)
from src.services.business import FEATURES
from src.utils.serialization import checksum

WINDOW_DAYS = 14

# 台账排除原因（页面与下载可直接展示）
REASON_LATE = '迟到记录：接收序号晚于本批截止点，仅可进入之后新建的批次'
REASON_OUTSIDE_WINDOW = '事件发生时间不在该读者到期前14日窗口内'
REASON_UNKNOWN_READER = '读者号不在名册，无法确定到期窗口'
REASON_ROSTER_AFTER_CUTOFF = '读者名册在本批截止之后才接入'
REASON_AFTER_EXPIRY = '事件发生在到期日当日或之后，防止到期后阅读泄漏'


def _parse_expire(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise HTTPException(422, f'到期日 {text!r} 不是 YYYY-MM-DD 日期') from exc


def _parse_ts(value):
    """接受毫秒/秒 epoch 数字或 ISO 8601 字符串，返回 UTC epoch 秒。"""
    if isinstance(value, bool):
        raise ValueError('布尔不是有效时间')
    if isinstance(value, (int, float)):
        ts = float(value)
        if abs(ts) > 1e14:  # 毫秒
            ts /= 1000.0
        return ts
    text = str(value).strip()
    if text.isdigit() or (text.startswith('-') and text[1:].isdigit()):
        ts = float(text)
        return ts / 1000.0 if abs(ts) > 1e14 else ts
    normalized = text.replace('Z', '+00:00')
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).timestamp()


def _event_payload(row):
    return {
        'reader_id': str(row['reader_id']).strip(),
        'session_id': str(row['session_id']).strip(),
        'issue_no': str(row['issue_no']).strip(),
        'occurred_at': row['occurred_at'],
        'completion_pct': float(row['completion_pct']),
    }


def _validate_event(row, index):
    required = ['event_id', 'reader_id', 'session_id', 'issue_no', 'occurred_at', 'completion_pct']
    for key in required:
        value = row.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise HTTPException(422, f'第 {index + 1} 行缺少字段 {key}')
    try:
        ts = _parse_ts(row['occurred_at'])
        completion = float(row['completion_pct'])
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(422, f'第 {index + 1} 行发生时间或完成率格式无效') from exc
    if not math.isfinite(ts) or not math.isfinite(completion) or not 0.0 <= completion <= 100.0:
        raise HTTPException(422, f'第 {index + 1} 行完成率须为 0~100 的有限数值，时间须有效')
    payload = _event_payload(row)
    payload['occurred_at'] = ts
    return str(row['event_id']).strip(), payload, ts, completion


def _window(expire_iso):
    end = date.fromisoformat(expire_iso) - timedelta(days=1)
    start = end - timedelta(days=WINDOW_DAYS - 1)
    return start, end


def upsert_roster(db, rows, actor, source='manual.json'):
    """接入/更新读者名册。重复 reader_id 以本次到期日覆盖并记录接收序号。"""
    if not rows:
        raise HTTPException(422, '名册至少需要一条读者记录')
    parsed, seen = [], set()
    for index, row in enumerate(rows):
        reader_id = str(row.get('reader_id', '')).strip()
        if not reader_id:
            raise HTTPException(422, f'第 {index + 1} 行缺少读者号 reader_id')
        if reader_id in seen:
            raise HTTPException(422, f'名册内 reader_id {reader_id} 重复，请先在文件内去重')
        seen.add(reader_id)
        expire_iso = _parse_expire(row.get('expire_date'))
        renewed = row.get('renewed')
        if renewed is not None and str(renewed).strip() != '':
            try:
                renewed = int(float(renewed))
                if renewed not in (0, 1):
                    raise ValueError
            except (TypeError, ValueError):
                raise HTTPException(422, f'第 {index + 1} 行 renewed 只能为 0 或 1')
        else:
            renewed = None
        parsed.append({'reader_id': reader_id, 'expire_date': expire_iso, 'renewed': renewed})

    last_no = db.scalar(select(func.coalesce(func.max(IngestionRun.last_receive_no), 0)))
    run = IngestionRun(kind='roster', source=source, offered=len(parsed), accepted=0,
                       last_receive_no=last_no, checksum=checksum(parsed),
                       created_by=actor, created_at=time.time())
    db.add(run)
    db.flush()
    accepted = 0
    for item in parsed:
        existing = db.scalar(select(ReaderRoster).where(ReaderRoster.reader_id == item['reader_id']))
        if existing:
            existing.expire_date = item['expire_date']
            existing.renewed = item['renewed'] if item['renewed'] is not None else existing.renewed
            existing.updated_receive_no = run.id
        else:
            db.add(ReaderRoster(reader_id=item['reader_id'], expire_date=item['expire_date'],
                                renewed=item['renewed'], updated_receive_no=run.id))
        accepted += 1
    run.accepted = accepted
    return run, accepted


def ingest_events(db, rows, actor, source='manual.json'):
    """原子接入阅读事件。

    - 事件号在上传内重复、或与库内同号异内容：整批拒绝（不写入任何一行）。
    - 与库内同号同内容：识别为重复投递，不多计（计入 duplicate_ids 供回执）。
    """
    if not rows:
        raise HTTPException(422, '至少需要一条阅读事件')
    normalized, seen = [], set()
    for index, row in enumerate(rows):
        event_id, payload, ts, completion = _validate_event(row, index)
        if event_id in seen:
            raise HTTPException(422, f'上传文件内事件号 {event_id} 重复，请先在文件内去重')
        seen.add(event_id)
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        normalized.append((event_id, payload, ts, completion, digest))

    existing = {e.event_id: e for e in db.scalars(
        select(ReadingEvent).where(ReadingEvent.event_id.in_([n[0] for n in normalized])))}
    duplicates = []
    for event_id, _payload, _ts, _completion, digest in normalized:
        prior = existing.get(event_id)
        if prior is None:
            continue
        if prior.payload_checksum != digest:
            raise HTTPException(
                409, f'事件号 {event_id} 已存在但内容不同：为避免污染台账，本次接入整批拒绝')
        duplicates.append(event_id)

    last_no = db.scalar(select(func.coalesce(func.max(IngestionRun.last_receive_no), 0)))
    fresh = [n for n in normalized if n[0] not in existing]
    run = IngestionRun(kind='events', source=source, offered=len(normalized), accepted=len(fresh),
                       last_receive_no=last_no + len(fresh),
                       checksum=checksum([n[4] for n in normalized]),
                       created_by=actor, created_at=time.time())
    db.add(run)
    db.flush()
    receive_no = last_no
    for event_id, payload, ts, completion, digest in fresh:
        receive_no += 1
        db.add(ReadingEvent(
            event_id=event_id, reader_id=payload['reader_id'], session_id=payload['session_id'],
            issue_no=payload['issue_no'], occurred_at=ts, completion_pct=completion,
            payload_checksum=digest, receive_no=receive_no,
            ingestion_run_id=run.id, received_at=time.time()))
    return run, len(fresh), duplicates


def _add_ledger(db, batch_id, event, decision, reason, detail=None):
    db.add(EventLedger(
        batch_id=batch_id, event_id=event.event_id, reader_id=event.reader_id,
        decision=decision, reason=reason, receive_no=event.receive_no,
        occurred_at=event.occurred_at, detail=detail or {}))


def _aggregate(events_in_window):
    """按口径聚合一个读者在窗口内的有效事件（已按 receive_no 排序）。"""
    sessions = {e.session_id for e in events_in_window}
    last_per_issue = {}
    for e in events_in_window:  # 同期取末次记录
        prior = last_per_issue.get(e.issue_no)
        if prior is None or e.occurred_at >= prior.occurred_at:
            last_per_issue[e.issue_no] = e
    completion_avg = sum(e.completion_pct for e in last_per_issue.values()) / len(last_per_issue)
    last_visit = max(e.occurred_at for e in events_in_window)
    issues = {e.issue_no for e in events_in_window}
    return len(sessions), round(completion_avg, 2), last_visit, len(issues)


def _build_one(db, batch, cutoff, roster_map):
    """构建单个窗口分组批次；成功返回 ready，异常标记 failed 并保留现场以便重试。"""
    window_end = date.fromisoformat(batch.window_end)
    window_start = date.fromisoformat(batch.window_start)
    start_ts = datetime(window_start.year, window_start.month, window_start.day,
                        tzinfo=timezone.utc).timestamp()
    # 到期日 00:00 UTC 为排他上界，天然排除到期当日及之后的事件
    end_exclusive_ts = start_ts + WINDOW_DAYS * 86400.0

    members = [r for r in roster_map.values()
               if date.fromisoformat(r.expire_date) - timedelta(days=1) == window_end]
    events = list(db.scalars(select(ReadingEvent).order_by(ReadingEvent.receive_no)))
    records, included_events = [], 0
    excluded = 0
    for reader in members:
        reader_events = [e for e in events if e.reader_id == reader.reader_id]
        in_window = []
        for e in reader_events:
            if e.receive_no > cutoff:
                _add_ledger(db, batch.id, e, 'excluded', REASON_LATE)
                excluded += 1
                continue
            if (reader.updated_receive_no or 0) > cutoff:
                _add_ledger(db, batch.id, e, 'excluded', REASON_ROSTER_AFTER_CUTOFF)
                excluded += 1
                continue
            if e.occurred_at >= end_exclusive_ts:
                _add_ledger(db, batch.id, e, 'excluded', REASON_AFTER_EXPIRY,
                            {'expire_date': reader.expire_date})
                excluded += 1
                continue
            if e.occurred_at < start_ts:
                _add_ledger(db, batch.id, e, 'excluded', REASON_OUTSIDE_WINDOW,
                            {'window_start': batch.window_start})
                excluded += 1
                continue
            _add_ledger(db, batch.id, e, 'included', '窗口内有效阅读事件')
            in_window.append(e)
            included_events += 1
        if not in_window:
            continue
        sessions, completion_avg, last_visit, issues = _aggregate(in_window)
        inactive_days = max(0, (window_end - datetime.fromtimestamp(
            last_visit, tz=timezone.utc).date()).days)
        record = {
            'reader_id': reader.reader_id,
            FEATURES[0]: sessions,
            FEATURES[1]: completion_avg,
            FEATURES[2]: inactive_days,
            FEATURES[3]: issues,
            'renewed': reader.renewed if reader.renewed is not None else 0,
        }
        records.append(record)

    # 名册中存在但不属于本窗口分组的读者，其事件归各自批次，不在本批留痕；
    # 仅对完全不在名册的事件按未知读者留痕（同样受截止点约束）。
    roster_ids = set(roster_map)
    for e in events:
        if e.reader_id in roster_ids or e.receive_no > cutoff:
            continue
        _add_ledger(db, batch.id, e, 'excluded', REASON_UNKNOWN_READER)
        excluded += 1

    records.sort(key=lambda r: r['reader_id'])
    dataset = Dataset(
        name=batch.name + ' · 汇总样本',
        source='experiment-batch-%d' % batch.id,
        records=records, checksum=checksum(records), created_at=time.time())
    db.add(dataset)
    db.flush()
    batch.dataset_id = dataset.id
    batch.included_readers = len(records)
    batch.included_events = included_events
    batch.excluded_events = excluded
    batch.status = 'ready'
    batch.finished_at = time.time()
    batch.error = ''


def build_batches(db, as_of: float | None = None):
    """为所有窗口已到期（window_end <= as_of）的窗口构建试验批次。

    - 每个窗口分组独立提交：中断重入时先回滚残留台账再重建，截止点不漂移。
    - ready 批次不可变；当窗口在最新批次截止点之后又收到新事件时，新建更高截止点的
      版本批次，迟到记录由此进入之后新建的批次（旧批次及其台账保持原样）。
    - 未写齐的 building 批次不挂 Dataset，不供试验使用。
    """
    as_of = time.time() if as_of is None else as_of
    current_cutoff = db.scalar(select(func.coalesce(func.max(ReadingEvent.receive_no), 0)))
    roster = list(db.scalars(select(ReaderRoster)))
    if not roster:
        return []
    eligible = {}
    for r in roster:
        start, end = _window(r.expire_date)
        if datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() <= as_of:
            eligible.setdefault(end.isoformat(), (start, end))

    existing = list(db.scalars(select(ExperimentBatch)))
    created = []
    roster_map = {r.reader_id: r for r in roster}
    for window_end_iso in sorted(eligible):
        start, end = eligible[window_end_iso]
        window_batches = [b for b in existing if b.window_end == window_end_iso]
        building = next((b for b in window_batches if b.status == 'building'), None)
        if building is not None:
            # 恢复路径：清掉上次中断可能写入的半成品台账，截止点固定为创建时的值
            for row in db.scalars(select(EventLedger).where(EventLedger.batch_id == building.id)):
                db.delete(row)
            db.commit()
            batch = building
        else:
            ready = sorted((b for b in window_batches if b.status == 'ready'),
                           key=lambda b: b.cutoff_receive_no or 0)
            member_ids = [r.reader_id for r in roster
                          if (_window(r.expire_date)[1]).isoformat() == window_end_iso]
            latest_cutoff = (ready[-1].cutoff_receive_no if ready else 0) or 0
            if ready:
                # 仅当本窗口成员在最新截止点之后有新事件或名册更新，才新建版本批次
                new_events = db.scalar(select(func.count()).select_from(ReadingEvent).where(
                    ReadingEvent.reader_id.in_(member_ids),
                    ReadingEvent.receive_no > latest_cutoff))
                roster_changed = any((r.updated_receive_no or 0) > latest_cutoff
                                     for r in roster if r.reader_id in member_ids)
                if not new_events and not roster_changed:
                    continue
            version = len(ready) + 1
            base = '试验批次 · 窗口截止 ' + window_end_iso
            name = base if version == 1 else '%s · 第%d版' % (base, version)
            if db.scalar(select(ExperimentBatch).where(ExperimentBatch.name == name)):
                name = '%s #%d' % (name, int(time.time()))
            batch = ExperimentBatch(
                name=name, window_end=end.isoformat(), window_start=start.isoformat(),
                cutoff_receive_no=current_cutoff, status='building', created_at=time.time())
            db.add(batch)
            db.commit()  # 先持久化 building 标记：后续构建回滚不会丢失恢复点
        try:
            _build_one(db, batch, batch.cutoff_receive_no, roster_map)
            db.commit()
        except Exception as exc:
            # 未写齐：回滚半成品，批次保持 building 并记录原因，不供试验使用
            db.rollback()
            stale = db.get(ExperimentBatch, batch.id)
            if stale is not None and stale.status == 'building':
                stale.error = str(exc)[:990]
                db.commit()
            raise
        created.append(db.get(ExperimentBatch, batch.id))
    return created
