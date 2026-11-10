"""Bounded, in-memory cleanup plans for managed completed artifacts."""
from __future__ import annotations

import hashlib
import asyncio
import json
import logging
from pathlib import Path
import stat
import time
from uuid import uuid4

from zhenzhen_gptimage.generation.admission import _finish_thread
from .retention_files import remove_verified, restore_quarantined


PLAN_TTL_MS = 10 * 60 * 1000
MAX_CANDIDATES = 1000
MAX_PLAN_BYTES = 1024 * 1024
RETENTION_MS = 90 * 24 * 60 * 60 * 1000


def _now():
    return time.time_ns() // 1_000_000


def _managed_identity(root: Path, row: dict, bucket: str = 'images') -> dict:
    root = root.resolve()
    if bucket not in ('images','responses','reference-staging'):
        raise ValueError('unknown managed bucket')
    images = root / bucket
    path = Path(row['local_path'])
    if not path.is_absolute() or path.parent != images:
        raise ValueError('unmanaged path')
    for part in (images, path):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise ValueError('link or reparse point')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size != row['bytes']:
        raise ValueError('file identity differs')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != row['sha256']:
        raise ValueError('file digest differs')
    return {'task_id': row['task_id'], 'image_index': row.get('image_index'),
            'local_path': str(path), 'sha256': row['sha256'], 'bytes': row['bytes'],
            'created_at': row['created_at'], 'device': info.st_dev, 'inode': info.st_ino,
            'mtime_ns': info.st_mtime_ns}


class RetentionService:
    def __init__(self, worker, data_dir: Path, locks, clock=_now):
        self.worker, self.data_dir, self.locks, self.clock = worker, data_dir, locks, clock
        self.plans = {}
        self._plan_lock = asyncio.Lock()
        self._policy_lock = asyncio.Lock()

    async def _auxiliary_candidates(self, task_id, planned_images, *, cutoff=None):
        """Only include registered recovery files once all task outputs qualify."""
        def snapshot(db):
            task = db.execute('SELECT status,response_ref FROM tasks WHERE task_id=?',(task_id,)).fetchone()
            if task is None or task['status'] != 'succeeded': return None
            images = [dict(row) for row in db.execute('''SELECT a.image_index,a.created_at,c.task_id AS cleaned
                FROM image_artifacts a LEFT JOIN artifact_cleanup_status c
                ON c.task_id=a.task_id AND c.image_index=a.image_index WHERE a.task_id=?''',(task_id,))]
            if not images or any(row['cleaned'] is None and row['image_index'] not in planned_images for row in images):
                return None
            newest = max(row['created_at'] for row in images)
            if cutoff is not None and newest >= cutoff: return None
            if db.execute("SELECT 1 FROM artifact_cleanup_events WHERE task_id=? AND state IN ('intent','uncertain') LIMIT 1",(task_id,)).fetchone():
                return None
            if db.execute("SELECT 1 FROM auxiliary_cleanup_events WHERE task_id=? AND state IN ('intent','uncertain') LIMIT 1",(task_id,)).fetchone():
                return None
            refs = [row['response_ref'] for row in db.execute('SELECT response_ref FROM attempts WHERE task_id=? AND response_ref IS NOT NULL',(task_id,))]
            if task['response_ref']: refs.append(task['response_ref'])
            refs = [ref for ref in refs if db.execute('''SELECT 1 FROM tasks WHERE task_id<>? AND response_ref=?
                UNION ALL SELECT 1 FROM attempts WHERE task_id<>? AND response_ref=? LIMIT 1''',
                (task_id,ref,task_id,ref)).fetchone() is None]
            references = [dict(row) for row in db.execute('''SELECT r.local_path,r.bytes,r.sha256 FROM reference_assets r
                WHERE r.task_id=? AND NOT EXISTS (SELECT 1 FROM reference_assets other
                    WHERE other.local_path=r.local_path AND other.task_id<>r.task_id)''',(task_id,))]
            unavailable = {row['source_path'] for row in db.execute("SELECT source_path FROM auxiliary_cleanup_events WHERE task_id=? AND state IN ('intent','uncertain','deleted')",(task_id,))}
            deleted = {row['source_path']:(row['expected_sha256'],row['expected_bytes']) for row in db.execute("SELECT source_path,expected_sha256,expected_bytes FROM auxiliary_cleanup_events WHERE task_id=? AND kind='response_body' AND state='deleted'",(task_id,))}
            return refs,references,newest,unavailable,deleted
        values = await self.worker.run(snapshot)
        if values is None: return []
        refs,references,created,unavailable,deleted = values
        from .retention_auxiliary import collect_auxiliary
        candidates = await asyncio.to_thread(collect_auxiliary,self.data_dir,task_id,refs,references,created,deleted)
        return [item for item in candidates if item['local_path'] not in unavailable]

    async def preview(self, *, before_ms: int | None = None, keep_latest: int | None = None):
        if (before_ms is None) == (keep_latest is None):
            raise ValueError('exactly one retention filter is required')
        if keep_latest is not None and keep_latest < 0:
            raise ValueError('keep_latest must be nonnegative')
        selected = []
        skipped = []
        skipped_truncated = False
        has_more = False
        plan_bytes = 0
        kept = 0
        cursor = None
        while True:
            def read_page(db):
                where = '' if cursor is None else 'AND (a.created_at,a.task_id,a.image_index)<(?,?,?)'
                params = () if cursor is None else cursor
                return [dict(row) for row in db.execute('''
                    SELECT a.*, t.status, EXISTS(SELECT 1 FROM artifact_cleanup_events e
                        WHERE e.task_id=a.task_id AND e.image_index=a.image_index AND e.state IN ('intent','uncertain')) AS cleanup_uncertain
                    FROM image_artifacts a JOIN tasks t ON t.task_id=a.task_id
                    LEFT JOIN artifact_cleanup_status c ON c.task_id=a.task_id AND c.image_index=a.image_index
                    WHERE c.task_id IS NULL ''' + where + '''
                    ORDER BY a.created_at DESC,a.task_id DESC,a.image_index DESC LIMIT 200''',params)]
            rows = await self.worker.run(read_page)
            if not rows: break
            for row in rows:
                cursor = (row['created_at'],row['task_id'],row['image_index'])
                reason = ('cleanup_requires_review' if row['cleanup_uncertain'] else
                          'task_not_complete' if row['status'] != 'succeeded' else None)
                if reason is None:
                    try:
                        identity = await asyncio.to_thread(_managed_identity, self.data_dir, row)
                    except (ValueError, OSError):
                        reason = 'unavailable_or_unmanaged'
                if reason is not None:
                    if len(skipped) < MAX_CANDIDATES:
                        skipped.append({'task_id':row['task_id'],'image_index':row['image_index'],'reason':reason})
                    else:
                        skipped_truncated = True
                    continue
                if keep_latest is not None and kept < keep_latest:
                    kept += 1
                    continue
                if before_ms is not None and identity['created_at'] >= before_ms:
                    continue
                encoded_size = len(json.dumps(identity,ensure_ascii=False).encode('utf-8'))
                if len(selected) == MAX_CANDIDATES or plan_bytes + encoded_size > MAX_PLAN_BYTES:
                    has_more = True
                    break
                selected.append(identity)
                plan_bytes += encoded_size
            if has_more or len(rows) < 200:
                break
        planned = {}
        for item in selected:
            planned.setdefault(item['task_id'],set()).add(item['image_index'])
        # Previously cleared tasks may still contain registered recovery
        # materials. Include them in a later plan, never silently delete them.
        seen = set(planned)
        for task_id, indices in planned.items():
            companions = await self._auxiliary_candidates(task_id,indices,cutoff=before_ms)
            companion_bytes = sum(len(json.dumps(item,ensure_ascii=False).encode('utf-8')) for item in companions)
            if len(selected)+len(companions) > MAX_CANDIDATES or plan_bytes+companion_bytes > MAX_PLAN_BYTES:
                has_more = True
                continue
            selected.extend(companions)
            plan_bytes += companion_bytes
        cursor_id = ''
        while True:
            def read_completed(db):
                return [row['task_id'] for row in db.execute('''SELECT t.task_id FROM tasks t
                    WHERE t.task_id>? AND t.status='succeeded'
                    AND EXISTS(SELECT 1 FROM image_artifacts a WHERE a.task_id=t.task_id)
                    AND NOT EXISTS(SELECT 1 FROM image_artifacts a LEFT JOIN artifact_cleanup_status c
                        ON c.task_id=a.task_id AND c.image_index=a.image_index
                        WHERE a.task_id=t.task_id AND c.task_id IS NULL)
                    ORDER BY t.task_id LIMIT 200''',(cursor_id,))]
            completed = await self.worker.run(read_completed)
            if not completed: break
            for task_id in completed:
                cursor_id = task_id
                if task_id in seen: continue
                companions = await self._auxiliary_candidates(task_id,set(),cutoff=before_ms)
                companion_bytes = sum(len(json.dumps(item,ensure_ascii=False).encode('utf-8')) for item in companions)
                if len(selected)+len(companions) > MAX_CANDIDATES or plan_bytes+companion_bytes > MAX_PLAN_BYTES:
                    has_more = True
                    break
                selected.extend(companions)
                plan_bytes += companion_bytes
            if has_more or len(completed)<200:
                break
        now = self.clock()
        self.plans = {key: plan for key, plan in self.plans.items() if plan['expires_at'] > now}
        if len(self.plans) >= 32:
            raise ValueError('too many active cleanup plans')
        plan_id = uuid4().hex
        plan = {'plan_id': plan_id, 'created_at': now, 'expires_at': now + PLAN_TTL_MS,
                'items': selected, 'count': len(selected), 'bytes': sum(item['bytes'] for item in selected),
                'skipped': skipped, 'skipped_truncated':skipped_truncated, 'has_more':has_more,
                'filter': {'before_ms': before_ms, 'keep_latest': keep_latest},
                'approved': False, 'consumed': False}
        self.plans[plan_id] = plan
        return plan

    async def approve(self, plan_id):
        async with self._plan_lock:
            plan = self.get_plan(plan_id)
            if plan['consumed']:
                raise ValueError('cleanup plan already consumed')
            plan['approved'] = True

    async def execute(self, plan_id):
        async with self._plan_lock:
            plan = self.get_plan(plan_id)
            if not plan['approved'] or plan['consumed']:
                raise ValueError('cleanup plan not authorized or already consumed')
            plan['consumed'] = True
        results = []
        for item in plan['items']:
            if item.get('kind'):
                results.append(await self._execute_auxiliary(item,'manual',plan_id))
            else:
                results.append(await self._execute_item(item, 'manual', plan_id))
        return {'plan_id':plan_id,'results':results}

    async def _execute_auxiliary(self, item, trigger_kind, plan_id):
        kind = item['kind']
        result = {'task_id':item['task_id'],'kind':kind,'local_path':item['local_path']}
        if kind not in ('response_body','response_manifest','reference_snapshot'):
            raise ValueError('invalid auxiliary kind')
        async with self.locks.hold(item['task_id']):
            def is_eligible(db):
                task = db.execute('SELECT status,response_ref FROM tasks WHERE task_id=?',(item['task_id'],)).fetchone()
                if task is None or task['status'] != 'succeeded': return False
                if db.execute('''SELECT 1 FROM image_artifacts a LEFT JOIN artifact_cleanup_status c
                    ON c.task_id=a.task_id AND c.image_index=a.image_index
                    WHERE a.task_id=? AND c.task_id IS NULL LIMIT 1''',(item['task_id'],)).fetchone(): return False
                if db.execute("SELECT 1 FROM artifact_cleanup_events WHERE task_id=? AND state IN ('intent','uncertain') LIMIT 1",(item['task_id'],)).fetchone(): return False
                if db.execute("SELECT 1 FROM auxiliary_cleanup_events WHERE task_id=? AND source_path=? AND state IN ('intent','uncertain','deleted') LIMIT 1",(item['task_id'],item['local_path'])).fetchone(): return False
                if kind == 'reference_snapshot':
                    return bool(db.execute('''SELECT 1 FROM reference_assets r WHERE r.task_id=? AND r.local_path=?
                        AND r.sha256=? AND r.bytes=? AND NOT EXISTS (SELECT 1 FROM reference_assets other
                        WHERE other.local_path=r.local_path AND other.task_id<>r.task_id)''',
                        (item['task_id'],item['local_path'],item['sha256'],item['bytes'])).fetchone())
                path = Path(item['local_path'])
                body = str(path.with_suffix('.body')) if kind == 'response_manifest' else str(path)
                if kind == 'response_manifest' and not db.execute("SELECT 1 FROM auxiliary_cleanup_events WHERE task_id=? AND source_path=? AND kind='response_body' AND state='deleted' LIMIT 1",(item['task_id'],body)).fetchone():
                    return False
                registered = task['response_ref']==body or bool(db.execute('SELECT 1 FROM attempts WHERE task_id=? AND response_ref=?',(item['task_id'],body)).fetchone())
                shared = db.execute('''SELECT 1 FROM tasks WHERE task_id<>? AND response_ref=? UNION ALL
                    SELECT 1 FROM attempts WHERE task_id<>? AND response_ref=? LIMIT 1''',
                    (item['task_id'],body,item['task_id'],body)).fetchone()
                return registered and not shared
            if not await self.worker.run(is_eligible):
                return dict(result,status='skipped')
            event_id=uuid4().hex
            item=dict(item,_cleanup_event_id=event_id)
            now=self.clock()
            await self.worker.run(lambda db:db.execute('''INSERT INTO auxiliary_cleanup_events
                (event_id,task_id,kind,source_path,expected_sha256,expected_bytes,trigger_kind,plan_id,state,detail,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,\'intent\',?,?,?)''',
                (event_id,item['task_id'],kind,item['local_path'],item['sha256'],item['bytes'],trigger_kind,
                 plan_id,json.dumps(item),now,now)))
            try:
                await _finish_thread(remove_verified,self.data_dir,item)
            except ValueError:
                status='skipped'
            except (OSError,NotImplementedError):
                status='failed'
            else:
                status='deleted'
            await self.worker.run(lambda db:db.execute('UPDATE auxiliary_cleanup_events SET state=?,updated_at=? WHERE event_id=?',(status,self.clock(),event_id)))
            return dict(result,status=status)

    async def _execute_item(self, item, trigger_kind, plan_id):
            async with self.locks.hold(item['task_id']):
                row = await self.worker.fetchone('''SELECT a.*,t.status FROM image_artifacts a
                    JOIN tasks t ON t.task_id=a.task_id LEFT JOIN artifact_cleanup_status c
                    ON c.task_id=a.task_id AND c.image_index=a.image_index
                    WHERE a.task_id=? AND a.image_index=? AND c.task_id IS NULL
                    AND NOT EXISTS (SELECT 1 FROM artifact_cleanup_events e WHERE e.task_id=a.task_id
                        AND e.image_index=a.image_index AND e.state IN ('intent','uncertain'))''',
                    (item['task_id'],item['image_index']))
                if (row is None or row['status'] != 'succeeded' or
                    any(row[key] != item[key] for key in ('local_path','sha256','bytes','created_at'))):
                    return {'task_id':item['task_id'],'image_index':item['image_index'],'status':'skipped'}
                event_id = uuid4().hex
                item = dict(item, _cleanup_event_id=event_id)
                now = self.clock()
                await self.worker.run(lambda db: db.execute('''INSERT INTO artifact_cleanup_events
                    (event_id,task_id,image_index,source_path,expected_sha256,expected_bytes,trigger_kind,
                     plan_id,state,detail,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'intent',?,?,?)''',
                    (event_id,item['task_id'],item['image_index'],item['local_path'],item['sha256'],
                     item['bytes'],trigger_kind,plan_id,json.dumps(item),now,now)))
                try:
                    await _finish_thread(remove_verified,self.data_dir,item)
                except ValueError:
                    await self.worker.run(lambda db: db.execute("UPDATE artifact_cleanup_events SET state='skipped',updated_at=? WHERE event_id=?",(self.clock(),event_id)))
                    status = 'skipped'
                except (OSError, NotImplementedError):
                    await self.worker.run(lambda db: db.execute("UPDATE artifact_cleanup_events SET state='failed',updated_at=? WHERE event_id=?",(self.clock(),event_id)))
                    status = 'failed'
                else:
                    def complete(db):
                        db.execute('BEGIN IMMEDIATE')
                        try:
                            db.execute("UPDATE artifact_cleanup_events SET state='deleted',updated_at=? WHERE event_id=?",(self.clock(),event_id))
                            db.execute('INSERT INTO artifact_cleanup_status VALUES (?,?,?,?)',
                                       (item['task_id'],item['image_index'],self.clock(),event_id))
                            db.commit()
                        except BaseException:
                            db.rollback()
                            raise
                    await self.worker.run(complete)
                    status = 'deleted'
                return {'task_id':item['task_id'],'image_index':item['image_index'],'status':status}

    async def policy(self):
        row = await self.worker.fetchone('SELECT enabled,updated_at FROM artifact_retention_policy WHERE singleton=1')
        return {'enabled': bool(row['enabled']), 'updated_at': row['updated_at'], 'retention_days': 90}

    async def set_policy(self, enabled: bool):
        async with self._policy_lock:
            await self.worker.run(lambda db: db.execute('UPDATE artifact_retention_policy SET enabled=?,updated_at=? WHERE singleton=1',
                                                        (int(enabled),self.clock())))
            return await self.policy()

    async def automatic_sweep(self):
        cutoff = self.clock() - RETENTION_MS
        cursor = 0
        results = []
        while True:
            rows = await self.worker.run(lambda db: [dict(row) for row in db.execute('''
                SELECT a.rowid AS row_number,a.* FROM image_artifacts a JOIN tasks t ON t.task_id=a.task_id
                LEFT JOIN artifact_cleanup_status c ON c.task_id=a.task_id AND c.image_index=a.image_index
                WHERE a.rowid>? AND a.created_at<? AND t.status='succeeded' AND c.task_id IS NULL
                  AND NOT EXISTS (SELECT 1 FROM artifact_cleanup_events e WHERE e.task_id=a.task_id
                      AND e.image_index=a.image_index AND e.state IN ('intent','uncertain'))
                ORDER BY a.rowid LIMIT 200''',(cursor,cutoff))])
            if not rows: break
            for row in rows:
                cursor = row['row_number']
                try:
                    item = await asyncio.to_thread(_managed_identity,self.data_dir,row)
                except (OSError, ValueError):
                    continue
                # Disabling waits for an in-flight deletion and prevents the
                # next one from starting, even if a sweep is already running.
                async with self._policy_lock:
                    if not (await self.policy())['enabled']:
                        return results
                    results.append(await self._execute_item(item,'automatic',None))
                    if len(results) >= MAX_CANDIDATES:
                        return results
        task_cursor = ''
        while True:
            task_ids = await self.worker.run(lambda db: [row['task_id'] for row in db.execute('''
                SELECT t.task_id FROM tasks t WHERE t.task_id>? AND t.status='succeeded'
                AND EXISTS(SELECT 1 FROM image_artifacts a WHERE a.task_id=t.task_id)
                AND NOT EXISTS(SELECT 1 FROM image_artifacts a LEFT JOIN artifact_cleanup_status c
                    ON c.task_id=a.task_id AND c.image_index=a.image_index
                    WHERE a.task_id=t.task_id AND (c.task_id IS NULL OR a.created_at>=?))
                ORDER BY t.task_id LIMIT 200''',(task_cursor,cutoff))])
            if not task_ids: break
            for task_id in task_ids:
                task_cursor = task_id
                items = await self._auxiliary_candidates(task_id,set(),cutoff=cutoff)
                for item in items:
                    async with self._policy_lock:
                        if not (await self.policy())['enabled']:
                            return results
                        results.append(await self._execute_auxiliary(item,'automatic',None))
                        if len(results) >= MAX_CANDIDATES:
                            return results
        return results

    async def automatic_loop(self, interval_seconds=3600):
        while True:
            try:
                if (await self.policy())['enabled']:
                    await self.automatic_sweep()
            except Exception:
                logging.getLogger(__name__).warning('Automatic cleanup failed; it will be retried on the next check')
            await asyncio.sleep(interval_seconds)

    async def reconcile_intents(self):
        for table in ('artifact_cleanup_events','auxiliary_cleanup_events'):
            rows = await self.worker.run(lambda db: [dict(row) for row in db.execute(f"SELECT * FROM {table} WHERE state='intent'")])
            for row in rows:
                async with self.locks.hold(row['task_id']):
                    state = 'uncertain'
                    try:
                        item = json.loads(row['detail'])
                        restored = await _finish_thread(restore_quarantined, self.data_dir, item)
                        if restored:
                            state = 'failed'
                        else:
                            kind=item.get('kind','image')
                            bucket={'image':'images','response_body':'responses','response_manifest':'responses',
                                    'reference_snapshot':'reference-staging'}[kind]
                            current = await _finish_thread(_managed_identity, self.data_dir, item, bucket)
                            if all(current[key] == item[key] for key in ('device','inode','mtime_ns','sha256','bytes')):
                                state = 'failed'
                    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                        pass
                    await self.worker.run(lambda db: db.execute(f"UPDATE {table} SET state=?,updated_at=? WHERE event_id=? AND state='intent'",(state,self.clock(),row['event_id'])))

    def get_plan(self, plan_id):
        plan = self.plans.get(plan_id)
        if plan is None or plan['expires_at'] <= self.clock():
            self.plans.pop(plan_id, None)
            raise ValueError('cleanup plan expired or missing')
        return plan
