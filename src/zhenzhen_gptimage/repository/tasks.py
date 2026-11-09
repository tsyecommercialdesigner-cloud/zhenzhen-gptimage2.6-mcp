"""Transactional task operations. Call only on the database worker thread."""
import json
import sqlite3
import base64
import hashlib
from uuid import uuid4
from zhenzhen_gptimage.generation.snapshot import IdempotencyConflict, input_digest

ACTIVE = ('queued','submitting','retry_wait','materializing','recovery_pending','unknown')

class QueueFull(ValueError): pass
class StateConflict(ValueError): pass

def accept_batch(db, requests, snapshots, now_ms, *, capacity=20, assets=None):
    if not 1 <= len(requests) <= 20 or len(requests) != len(snapshots) or not 1 <= capacity <= 20:
        raise ValueError('invalid batch')
    if assets is None:
        assets = [None] * len(requests)
    if len(assets) != len(requests):
        raise ValueError('asset list must match batch')
    db.execute('BEGIN IMMEDIATE')
    try:
        existing = {}
        fresh = {}
        for request, snap, refs in zip(requests, snapshots, assets):
            digest = input_digest(request)
            key = request.idempotency_key
            if key in existing:
                if existing[key]['input_digest'] != digest:
                    raise IdempotencyConflict(key)
                continue
            row = db.execute('SELECT * FROM tasks WHERE idempotency_key=?', (key,)).fetchone()
            if row is not None:
                if row['input_digest'] != digest: raise IdempotencyConflict(key)
                existing[key] = dict(row)
            else:
                if snap is None or snap.input_digest != digest:
                    raise ValueError('missing or invalid snapshot')
                if refs is None: refs = []
                if len(refs) != len(request.references):
                    raise ValueError('reference snapshots required for new requests')
                if tuple(ref['sha256'] for ref in refs) != snap.reference_hashes:
                    raise ValueError('reference hashes do not match snapshot')
                fresh[key] = (request, snap, refs)
                existing[key] = {'task_id': str(uuid4()), 'input_digest':digest}
        count = db.execute('SELECT count(*) FROM tasks WHERE status IN (?,?,?,?,?,?)', ACTIVE).fetchone()[0]
        if count + len(fresh) > capacity: raise QueueFull('unfinished task capacity exceeded')
        batch_id = str(uuid4())
        db.execute('INSERT INTO batches VALUES (?,?)', (batch_id, now_ms))
        for key, (request, snap, refs) in fresh.items():
            task_id = existing[key]['task_id']
            db.execute('''INSERT INTO tasks(task_id,batch_id,idempotency_key,channel,family,width,height,resolved_model,
                input_digest,resolved_digest,snapshot_json,status,created_at,updated_at,deadline_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)''',
                (task_id,batch_id,key,snap.channel,request.family,snap.width,snap.height,snap.resolved_model,
                 snap.input_digest,snap.resolved_digest,snap.model_dump_json(),now_ms,now_ms,now_ms+600000))
            db.execute('INSERT INTO task_events(task_id,to_status,reason_code,created_at) VALUES (?,?,?,?)', (task_id,'queued','accepted',now_ms))
            for index, ref in enumerate(refs):
                db.execute('''INSERT INTO reference_assets(asset_id,task_id,input_index,local_path,source_kind,sha256,mime_type,bytes,width,height)
                              VALUES (?,?,?,?,'local_file',?,?,?,?,?)''',
                           (ref.get('asset_id') or str(uuid4()),task_id,index,ref['local_path'],ref['sha256'],ref['mime_type'],ref['bytes'],ref['width'],ref['height']))
        seen=set()
        for index, request in enumerate(requests):
            key=request.idempotency_key
            reused=key not in fresh or key in seen
            db.execute('INSERT INTO batch_items VALUES (?,?,?,?)',(batch_id,index,existing[key]['task_id'],int(reused)))
            seen.add(key)
        db.commit()
        return batch_id, [existing[r.idempotency_key]['task_id'] for r in requests]
    except BaseException:
        db.rollback()
        raise

def start_attempt(db, task_id, revision, now_ms):
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT status,attempt_count,deadline_at,next_attempt_at FROM tasks WHERE task_id=? AND revision=?',(task_id,revision)).fetchone()
        if row is None or row['status'] not in ('queued','retry_wait') or row['attempt_count']>=3 or now_ms>=row['deadline_at'] or (row['status']=='retry_wait' and now_ms<row['next_attempt_at']):
            raise StateConflict('task cannot start')
        attempt=row['attempt_count']+1
        db.execute("INSERT INTO attempts(task_id,attempt_no,started_at,submission_certainty) VALUES (?,?,?,'prepared')",(task_id,attempt,now_ms))
        db.execute("UPDATE tasks SET status='submitting',attempt_count=?,updated_at=?,next_attempt_at=NULL,revision=revision+1 WHERE task_id=? AND revision=?",(attempt,now_ms,task_id,revision))
        db.execute('INSERT INTO task_events(task_id,from_status,to_status,reason_code,created_at) VALUES (?,?,?,?,?)',(task_id,row['status'],'submitting','attempt_prepared',now_ms))
        db.commit()
        return attempt
    except BaseException:
        db.rollback()
        raise

_TRANSITIONS = {
    'queued': {'expired','cancelled','failed'}, 'retry_wait': {'expired','cancelled','failed'},
    'submitting': {'retry_wait','unknown','failed','materializing'},
    'materializing': {'succeeded','recovery_pending'},
    'recovery_pending': {'materializing','closed'}, 'unknown': {'closed'},
}

def transition(db, task_id, revision, target, now_ms, *, reason, next_attempt_at=None,
               response_ref=None, error_category=None, error_message=None,
               attempt_certainty=None, http_status=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT status,attempt_count FROM tasks WHERE task_id=? AND revision=?',(task_id,revision)).fetchone()
        if row is None or target not in _TRANSITIONS.get(row['status'], set()):
            raise StateConflict('invalid state or revision')
        if target == 'closed':
            raise ValueError('use explicit closure operation')
        if target == 'materializing' and row['status'] == 'submitting' and not response_ref:
            raise ValueError('complete response reference required')
        if target == 'retry_wait' and next_attempt_at is None:
            raise ValueError('retry time required')
        if target == 'retry_wait' and attempt_certainty not in ('not_sent', 'rejected'):
            raise ValueError('retry requires evidence of safe failure')
        if row['status'] == 'submitting' and attempt_certainty is None:
            raise ValueError('finishing submission requires attempt outcome')
        if attempt_certainty is not None:
            result=db.execute('''UPDATE attempts SET finished_at=?,submission_certainty=?,http_status=?,error_category=?,error_message=?,response_ref=?
                WHERE task_id=? AND attempt_no=? AND finished_at IS NULL''',
                (now_ms,attempt_certainty,http_status,error_category,error_message,response_ref,task_id,row['attempt_count']))
            if result.rowcount != 1: raise StateConflict('attempt changed')
        db.execute('''UPDATE tasks SET status=?,updated_at=?,next_attempt_at=?,response_ref=COALESCE(?,response_ref),
                      error_category=?,error_message=?,revision=revision+1 WHERE task_id=? AND revision=?''',
                   (target,now_ms,next_attempt_at,response_ref,error_category,error_message,task_id,revision))
        db.execute('INSERT INTO task_events(task_id,from_status,to_status,reason_code,created_at) VALUES (?,?,?,?,?)',
                   (task_id,row['status'],target,reason,now_ms))
        db.commit()
    except BaseException:
        db.rollback()
        raise

def list_tasks(db, *, status=None, batch_id=None, model=None, created_from=None, created_to=None, limit=20, cursor=None):
    if not 1 <= limit <= 100:
        raise ValueError('invalid page size')
    filters={'status':status,'batch_id':batch_id,'model':model,'created_from':created_from,'created_to':created_to,'limit':limit}
    digest=hashlib.sha256(json.dumps(filters,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    position=None
    if cursor:
        try:
            obj=json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor)%4)))
            if obj['filter'] != digest or type(obj['time']) is not int or not isinstance(obj['id'],str): raise ValueError()
            position=(obj['time'],obj['id'])
        except (ValueError,KeyError,TypeError,UnicodeError):
            raise ValueError('invalid cursor') from None
    clauses=[]; params=[]
    for field,value in (('t.status',status),('t.resolved_model',model)):
        if value is not None: clauses.append(field+'=?'); params.append(value)
    if batch_id is not None:
        clauses.append('EXISTS (SELECT 1 FROM batch_items b WHERE b.task_id=t.task_id AND b.batch_id=?)');params.append(batch_id)
    if created_from is not None: clauses.append('t.created_at>=?');params.append(created_from)
    if created_to is not None: clauses.append('t.created_at<?');params.append(created_to)
    if position: clauses.append('(t.created_at<? OR (t.created_at=? AND t.task_id<?))');params.extend((position[0],position[0],position[1]))
    query='SELECT t.* FROM tasks t'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY t.created_at DESC,t.task_id DESC LIMIT ?'
    rows=[dict(r) for r in db.execute(query,(*params,limit+1)).fetchall()]
    next_cursor=None
    if len(rows)>limit:
        rows=rows[:limit]; last=rows[-1]
        raw=json.dumps({'filter':digest,'time':last['created_at'],'id':last['task_id']},separators=(',',':')).encode()
        next_cursor=base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return rows,next_cursor

def publish_images(db, task_id, revision, images, now_ms):
    if not 1 <= len(images) <= 4:
        raise ValueError('invalid image count')
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT status FROM tasks WHERE task_id=? AND revision=?',(task_id,revision)).fetchone()
        if row is None or row['status'] != 'materializing':
            raise StateConflict('task not materializing')
        for i, image in enumerate(images):
            if image.image_index != i: raise ValueError('noncontiguous image indices')
            db.execute('''INSERT INTO image_artifacts(task_id,image_index,local_path,sha256,mime_type,bytes,width,height,revised_prompt,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',(task_id,i,image.local_path,image.sha256,image.mime_type,image.bytes,image.width,image.height,image.revised_prompt,now_ms))
        db.execute("UPDATE tasks SET status='succeeded',updated_at=?,revision=revision+1 WHERE task_id=? AND revision=?",(now_ms,task_id,revision))
        db.execute("INSERT INTO task_events(task_id,from_status,to_status,reason_code,created_at) VALUES (?,'materializing','succeeded','published',?)",(task_id,now_ms))
        db.commit()
    except BaseException:
        db.rollback()
        raise
