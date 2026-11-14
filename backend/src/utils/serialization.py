import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def roster_dict(r):
    return {'id':r.id,'reader_id':r.reader_id,'expire_date':r.expire_date,
            'renewed':r.renewed,'updated_receive_no':r.updated_receive_no}
def event_dict(e):
    return {'id':e.id,'event_id':e.event_id,'reader_id':e.reader_id,'session_id':e.session_id,
            'issue_no':e.issue_no,'occurred_at':e.occurred_at,'completion_pct':e.completion_pct,
            'receive_no':e.receive_no,'ingestion_run_id':e.ingestion_run_id,'received_at':e.received_at}
def run_dict(r):
    return {'id':r.id,'kind':r.kind,'source':r.source,'offered':r.offered,'accepted':r.accepted,
            'last_receive_no':r.last_receive_no,'checksum':r.checksum,
            'created_by':r.created_by,'created_at':r.created_at}
def batch_dict(b):
    return {'id':b.id,'name':b.name,'window_start':b.window_start,'window_end':b.window_end,
            'cutoff_receive_no':b.cutoff_receive_no,'status':b.status,'dataset_id':b.dataset_id,
            'included_readers':b.included_readers,'included_events':b.included_events,
            'excluded_events':b.excluded_events,'error':b.error,
            'created_at':b.created_at,'finished_at':b.finished_at}
def ledger_dict(x):
    return {'id':x.id,'batch_id':x.batch_id,'event_id':x.event_id,'reader_id':x.reader_id,
            'decision':x.decision,'reason':x.reason,'receive_no':x.receive_no,
            'occurred_at':x.occurred_at,'detail':x.detail}
