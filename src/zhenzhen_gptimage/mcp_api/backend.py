"""Business adapter for the MCP surface; no transport-specific state."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import time
from uuid import uuid4
from zhenzhen_gptimage.artifacts.output import ImageResultError, ImageDownloadError
from zhenzhen_gptimage.artifacts.storage import ResourceLimitError
from zhenzhen_gptimage.providers.t8_star.client import ProviderError
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.contracts import SaveTemplateInput, ErrorCode, TOOL_INPUTS
from zhenzhen_gptimage.generation.snapshot import IdempotencyConflict
from zhenzhen_gptimage.prompts.templates import get_template, save_template, list_templates, render_template, TemplateConflict
from zhenzhen_gptimage.repository.tasks import list_tasks, QueueFull, StateConflict

def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace('+00:00','Z')

def millis(value):
    if value is None: return None
    date = datetime.fromisoformat(value.replace('Z','+00:00'))
    if date.tzinfo is None: raise ValueError('timestamp must include timezone')
    return int(date.timestamp()*1000)

def success(data, warnings=()): return {'ok':True,'data':data,'error':None,'warnings':list(warnings)}
def failure(code, message, action, *, data=None, task_id=None, phase=None, reason=None, can_retry_recovery=False):
    error={'code':code,'message':message,'next_action':action,'retryable':False}
    if task_id is not None: error['task_id']=task_id
    if phase is not None:
        error['diagnostic'] = {'phase': phase, 'reason': reason, 'can_retry_recovery': can_retry_recovery}
    return {'ok':False,'data':data,'warnings':[],'error':error}

class ServiceBackend:
    def __init__(self, worker, generation, recovery=None, export_root=None, retention=None):
        self.worker, self.generation, self.recovery = worker, generation, recovery
        self.export_root = export_root
        self.retention = retention
        self._recovery_plans = {}

    async def _task(self, row):
        row = dict(row)
        images = await self.worker.run(lambda db: [dict(r) for r in db.execute('SELECT * FROM image_artifacts WHERE task_id=? ORDER BY image_index',(row['task_id'],))])
        if row['status']=='recovery_pending' and not images:
            images=await self.worker.run(lambda db:[dict(r) for r in db.execute('SELECT * FROM pending_image_artifacts WHERE task_id=? ORDER BY image_index',(row['task_id'],))])
        for image in images:
            image.pop('revised_prompt',None); image.pop('created_at',None)
            cleaned=await self.worker.fetchone('SELECT cleaned_at FROM artifact_cleanup_status WHERE task_id=? AND image_index=?',(row['task_id'],image['image_index']))
            image['cleaned'] = cleaned is not None
            uncertain=await self.worker.fetchone("SELECT 1 FROM artifact_cleanup_events WHERE task_id=? AND image_index=? AND state='uncertain' UNION ALL SELECT 1 FROM auxiliary_cleanup_events WHERE task_id=? AND state='uncertain' LIMIT 1",(row['task_id'],image['image_index'],row['task_id']))
            image['cleanup_uncertain'] = uncertain is not None
            pending_metadata=image.pop('metadata_json',None)
            meta=await self.worker.fetchone('SELECT metadata_json FROM image_format_metadata WHERE task_id=? AND image_index=?',(row['task_id'],image['image_index']))
            if pending_metadata is not None or meta is not None:
                image['metadata']=json.loads(pending_metadata if pending_metadata is not None else meta['metadata_json'])
            if cleaned is not None:
                image['available'] = False
            elif self.recovery is not None:
                if pending_metadata is not None:
                    import asyncio
                    if row['error_category'] == 'SIZE_MISMATCH':
                        image['available'] = await asyncio.to_thread(self.recovery._verify_candidate, image)
                    else:
                        from zhenzhen_gptimage.artifacts.recovery import _read_image
                        image['available'],_=await asyncio.to_thread(_read_image,image,False,1,1)
                else:
                    current,_=await self.recovery.image(row['task_id'],image['image_index'],False)
                    image['available'] = current['available']
            else:
                from pathlib import Path
                image['available'] = Path(image['local_path']).is_file()
        actions = {'unknown':['close_task'], 'recovery_pending':['recover_task','close_task'], 'succeeded':['get_image']}.get(row['status'],[])
        remote=await self.worker.fetchone('SELECT remote_id,remote_status FROM remote_tasks WHERE task_id=?',(row['task_id'],))
        if remote is not None and row['status']=='unknown': actions=['recover_task','close_task']
        if remote is not None and remote['remote_status'] not in ('SUCCESS', 'FAILURE') and 'close_task' in actions:
            actions.remove('close_task')
        if row['status'] == 'closed':
            actions = ['inspect_closed_artifact']
        if row['status']=='recovery_pending' and images and images[0].get('mime_type')=='image/gif':
            actions = actions + ['accept_gif_size']
        view = {'task_id':row['task_id'],'batch_id':row['batch_id'], 'idempotency_key':row['idempotency_key'],
                'status':row['status'],'resolved_model':row['resolved_model'],'channel':row['channel'],
                'width':row['width'],'height':row['height'],'created_at':iso(row['created_at']),
                'deadline_at':iso(row['deadline_at']),'attempt_count':row['attempt_count'],
                'images':images,'error_category':row['error_category'],'allowed_actions':actions,
                'remote_task': dict(remote) if remote is not None else None}
        if 'close_task' in actions:
            view['close_requires_confirmation'] = True
        if row['status'] in ('unknown', 'recovery_pending'):
            view['recovery_mode'] = ('check_same_remote_task' if remote is not None and row['status'] == 'unknown'
                                     else 'process_saved_response' if row['response_ref'] and row['status'] == 'recovery_pending'
                                     else 'no_response_evidence')
            if view['recovery_mode'] == 'no_response_evidence' and 'recover_task' in actions:
                actions.remove('recover_task')
        if row['status'] == 'recovery_pending' and row['error_category'] == 'SIZE_MISMATCH':
            candidate = await self.worker.fetchone('SELECT digest FROM static_size_candidates WHERE task_id=?', (row['task_id'],))
            if candidate is not None:
                view['recovery_mode'] = 'use_saved_static_images'
                if images and all(image['available'] for image in images):
                    if 'recover_task' not in actions:
                        actions.insert(0, 'recover_task')
                    actions.append('accept_static_size')
                view['size_mismatch'] = {
                    'requested': {'width': row['width'], 'height': row['height']},
                    'candidate_digest': candidate['digest'],
                    'actual': [{key: image[key] for key in ('image_index','width','height','sha256','available')} for image in images],
                    'next_action': '调用 recover_task 原样登记已有候选，无需重新生成',
                }
        elif row['status'] == 'succeeded' and row['channel'] in ('images', 'flux') and images:
            requested = (row['width'], row['height'])
            static_types = {'image/png', 'image/jpeg', 'image/webp'}
            if all(image['mime_type'] in static_types for image in images) and any(
                (image['width'], image['height']) != requested for image in images
            ):
                view['size_mismatch'] = {
                    'code': 'SIZE_MISMATCH',
                    'requested': {'width': requested[0], 'height': requested[1]},
                    'actual': [{key: image[key] for key in ('image_index','width','height','sha256','available')} for image in images],
                }
        return view

    @staticmethod
    def _size_warnings(*views):
        return [
            f"SIZE_MISMATCH: 任务 {view['task_id']} 的实际尺寸与请求不同，已按原始尺寸保存"
            for view in views if view['status'] == 'succeeded' and 'size_mismatch' in view
        ]

    @staticmethod
    def _template(row):
        if row is None: raise KeyError('template')
        out=dict(row); out['variables']=json.loads(out.pop('variables_json'))
        out['created_at']=iso(out['created_at']);out['updated_at']=iso(out['updated_at'])
        return out

    async def _prepare_recovery(self, args):
        action = args['action']
        if action not in ('close_task', 'accept_static_size', 'export_closed_artifact'):
            raise ValueError('invalid recovery action')
        values = TOOL_INPUTS[action].model_validate(args['arguments']).model_dump()
        task_id = values['task_id']
        row = await self.recovery._row(task_id)
        if action == 'close_task':
            if row['status'] == 'closed':
                return success(await self._task(row))
            if row['status'] != values['expected_status']:
                raise StateConflict('closure state changed')
            remote = await self.worker.fetchone('SELECT remote_status FROM remote_tasks WHERE task_id=?', (task_id,))
            if remote is not None and remote['remote_status'] not in ('SUCCESS', 'FAILURE'):
                raise StateConflict('remote task still active')
            values['expected_revision'] = row['revision']
            summary = {'effect': '结束常规恢复并释放队列容量，不取消供应商请求',
                       'file_status': '可在结案后检查现有原件' if row['response_ref'] else '目前无已持久化的响应',
                       'reason': values['reason'], 'status': row['status']}
        elif action == 'accept_static_size':
            view = await self._task(row)
            mismatch = view.get('size_mismatch')
            if mismatch is None and row['status'] == 'succeeded':
                record = await self.worker.fetchone('SELECT digest FROM static_size_candidates WHERE task_id=? AND accepted_at IS NOT NULL',(task_id,))
                if record is not None and record['digest'] == values['candidate_digest']:
                    return success(view)
            if mismatch is None or mismatch['candidate_digest'] != values['candidate_digest'] or 'accept_static_size' not in view['allowed_actions']:
                raise StateConflict('candidate no longer available')
            summary = {'effect': '原样登记全部候选图片为成功结果', **mismatch}
        else:
            candidate = await self.recovery.closed_candidate(task_id, values['image_index'])
            if candidate['sha256'] != values['sha256']:
                raise StateConflict('candidate changed')
            from pathlib import Path
            from zhenzhen_gptimage.artifacts.export_paths import validate_export_destination
            try:
                destination = validate_export_destination(self.export_root, Path(values['destination']))
            except FileExistsError:
                return failure('STATE_CONFLICT', '目标文件已存在', '选择其他目标路径')

            summary = {'effect': '复制原件，保留任务结案状态', 'candidate': candidate, 'destination': str(destination)}
        now = time.monotonic()
        self._recovery_plans = {key: item for key, item in self._recovery_plans.items() if item[0] > now}
        if len(self._recovery_plans) >= 100:
            return failure('RESOURCE_LIMIT', '待确认操作过多', '稍后重新申请')
        plan_id = uuid4().hex
        details = {'plan_id': plan_id, 'action': action, 'task_id': task_id, 'expires_in_seconds': 300, **summary}
        self._recovery_plans[plan_id] = (now + 300, details, values)
        return success(details)

    def _recovery_plan(self, plan_id, consume=False):
        item = self._recovery_plans.pop(plan_id, None) if consume else self._recovery_plans.get(plan_id)
        if item is None or item[0] <= time.monotonic():
            raise StateConflict('approval expired')
        return item[1:]

    async def _execute_recovery(self, plan_id):
        details, args = self._recovery_plan(plan_id, consume=True)
        action = details['action']
        if action == 'close_task':
            return await self._recovery_call(action, args)
        if action == 'accept_static_size':
            row = await self.recovery.accept_static(args['task_id'], args['candidate_digest'])
            return await self._add_preview(success(await self._task(row), ['已按用户确认登记实际尺寸']), args['task_id'])
        try:
            return success(await self.recovery.export_closed(args['task_id'], args['image_index'], args['sha256'],
                                 args['destination'], self.export_root))
        except FileExistsError:
            return failure('STATE_CONFLICT', '目标文件已存在', '选择其他目标路径')
        except (OSError, ValueError):
            return failure('ARTIFACT_UNAVAILABLE', '原件或目标路径未通过导出校验', '检查原件和目标路径')

    async def _recovery_call(self, name, args):
        if name == 'recover_task':
            task_id = args['task_id']
            try:
                row = await self.recovery.recover(task_id)
            except (ImageResultError, ImageDownloadError, ResourceLimitError, ProviderError,
                    OSError, ValueError, StateConflict, TimeoutError) as exc:
                current = await self.recovery._row(task_id)
                view = await self._task(current)
                reason, message, retry = (
                    ('state_conflict', '当前任务状态或保存的响应不允许恢复', False) if isinstance(exc, StateConflict) else
                    ('download_failed', '无法下载已有响应中的图片', True) if isinstance(exc, ImageDownloadError) else
                    ('deadline', '恢复超过时间预算', True) if isinstance(exc, TimeoutError) else
                    ('file_error', '无法读取或保存恢复文件', True) if isinstance(exc, OSError) else
                    ('resource_limit', '结果超过资源限制', False) if isinstance(exc, ResourceLimitError) else
                    ('invalid_result', '已有结果未通过解析或验证', False)
                )
                return failure('STATE_CONFLICT' if isinstance(exc, StateConflict) else 'ARTIFACT_UNAVAILABLE',
                               message, '查看当前任务状态与恢复证据，保留原任务，不重新提交',
                               data=view, task_id=task_id, phase='recovery', reason=reason,
                               can_retry_recovery=retry)
            view = await self._task(row)
            result = success(view, self._size_warnings(view))
            return await self._add_preview(result,args['task_id']) if row['status']=='succeeded' else result
        if name == 'close_task':
            row,_=await self.recovery.close(args['task_id'],args['expected_status'],args['reason'],args.get('expected_revision'))
            return success(await self._task(row))
        if name == 'accept_gif_size':
            row=await self.recovery.accept_gif_size(args['task_id'],args['sha256'],args['width'],args['height'])
            return await self._add_preview(success(await self._task(row)),args['task_id'])
        cleaned=await self.worker.fetchone('SELECT cleaned_at FROM artifact_cleanup_status WHERE task_id=? AND image_index=?',(args['task_id'],args.get('image_index',0)))
        uncertain=await self.worker.fetchone("SELECT 1 FROM artifact_cleanup_events WHERE task_id=? AND image_index=? AND state='uncertain' UNION ALL SELECT 1 FROM auxiliary_cleanup_events WHERE task_id=? AND state='uncertain' LIMIT 1",(args['task_id'],args.get('image_index',0),args['task_id']))
        if cleaned is not None:
            row=await self.worker.fetchone('SELECT * FROM image_artifacts WHERE task_id=? AND image_index=?',(args['task_id'],args.get('image_index',0)))
            if row is None: raise KeyError('image')
            row=dict(row);row['available']=False;preview=None
        else:
            row, preview=await self.recovery.image(args['task_id'],args.get('image_index',0),args.get('include_preview',True))
            row=dict(row)
        row.pop('created_at',None);row.pop('revised_prompt',None)
        row['cleaned'] = cleaned is not None
        row['cleanup_uncertain'] = uncertain is not None
        meta=await self.worker.fetchone('SELECT metadata_json FROM image_format_metadata WHERE task_id=? AND image_index=?',(args['task_id'],args.get('image_index',0)))
        if meta is not None: row['metadata']=json.loads(meta['metadata_json'])
        if not row['available']:
            message = '图片原件已清理' if cleaned is not None else ('清理结果不明' if uncertain is not None else '图片文件不可用')
            action = '检查清理账本及工作区导出副本' if uncertain is not None else ('检查历史或工作区导出副本' if cleaned is not None else '检查本地文件')
            return failure('ARTIFACT_UNAVAILABLE',message,action,data=row,task_id=args['task_id'])
        result=success(row)
        if args.get('include_preview',True) and preview is None:
            result['warnings'].append('预览不可用，原图仍可使用')
        if preview is not None: result['_preview']=preview
        if row['mime_type']=='image/gif' and preview is not None: result['warnings'].append('预览为 GIF 静态首帧，原文件保留动画')
        return result

    async def _add_preview(self, result, task_id):
        if self.recovery is None: return result
        try:
            row, preview = await self.recovery.image(task_id,0,True)
            if row['available'] and preview is not None:
                result['_preview']=preview
                if row['mime_type']=='image/gif': result['warnings'].append('预览为 GIF 静态首帧，原文件保留动画')
            else:
                result['warnings'].append('预览不可用，原图仍可使用')
        except (KeyError, OSError, ValueError):
            result['warnings'].append('预览不可用，原图仍可使用')
        return result

    async def call(self, name, args):
        try:
            if name == '__cleanup_plan__':
                if self.retention is None:
                    return failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置')
                return success(self.retention.get_plan(args['plan_id']))
            if name == '__retention_policy__':
                if self.retention is None: return failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置')
                return success(await self.retention.policy())
            if name == '__set_retention_policy__':
                if self.retention is None: return failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置')
                if type(args.get('enabled')) is not bool: raise ValueError('invalid policy')
                return success(await self.retention.set_policy(args['enabled']))
            if name == 'get_retention_policy':
                if self.retention is None: return failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置')
                return success(await self.retention.policy())
            if name == '__approve_cleanup__':
                if self.retention is None:
                    return failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置')
                await self.retention.approve(args['plan_id'])
                return success({'plan_id':args['plan_id'],'approved':True})
            if name == 'preview_cleanup':
                if self.retention is None:
                    return failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置')
                return success(await self.retention.preview(before_ms=millis(args.get('before')),
                                                            keep_latest=args.get('keep_latest')))
            if name == 'execute_cleanup':
                if self.retention is None:
                    return failure('CONFIG_ERROR','清理功能尚未接入','检查服务配置')
                return success(await self.retention.execute(args['plan_id']))
            if name == 'export_image':
                if self.recovery is None:
                    return failure('CONFIG_ERROR','导出功能尚未接入','检查服务配置')
                from pathlib import Path
                from zhenzhen_gptimage.artifacts.export import export_original
                from zhenzhen_gptimage.generation.admission import _finish_thread
                async with self.recovery.locks.hold(args['task_id']):
                    row = await self.worker.fetchone('''SELECT a.* FROM image_artifacts a JOIN tasks t ON t.task_id=a.task_id
                        LEFT JOIN artifact_cleanup_status c ON c.task_id=a.task_id AND c.image_index=a.image_index
                        WHERE a.task_id=? AND a.image_index=? AND t.status='succeeded' AND c.task_id IS NULL''',
                        (args['task_id'], args.get('image_index', 0)))
                    if row is None:
                        raise KeyError('image')
                    try:
                        result = await _finish_thread(export_original, dict(row), self.export_root, Path(args['destination']))
                    except FileExistsError:
                        return failure('STATE_CONFLICT','目标文件已存在','选择其他目标路径')
                    except (OSError, ValueError):
                        return failure('ARTIFACT_UNAVAILABLE','无法安全导出原件','检查原件、目标路径和权限')
                    return success(result)
            if name == 'get_capabilities':
                from .server import capabilities
                return success(capabilities())
            if name == '__resource__':
                from .server import capabilities
                from zhenzhen_gptimage.prompts.guidance import PROMPT_GUIDE, RECOVERY_GUIDE
                resources = {'gptimage://capabilities': json.dumps(capabilities(), ensure_ascii=False),
                             'gptimage://prompt-guide': PROMPT_GUIDE,
                             'gptimage://recovery-guide': RECOVERY_GUIDE}
                return success(resources[args['uri']])
            if name == '__prompt__':
                from zhenzhen_gptimage.prompts.guidance import optimize_ecommerce_prompt
                return success(optimize_ecommerce_prompt(args['requirement'], args['product_facts'], args['image_purpose']))
            if name == 'generate_image':
                request=GenerationRequest.model_validate(args['request'])
                row=await self.generation.generate_image(request)
                view=await self._task(row)
                if request.execution_mode=='async' and view['status'] in ('queued','submitting','retry_wait','materializing'):
                    return success(view)
                if row['status'] == 'recovery_pending' and row['error_category'] == 'SIZE_MISMATCH' and self.recovery:
                    return await self._recovery_call('recover_task', {'task_id': row['task_id']})
                if view['status'] != 'succeeded':
                    code=view['error_category'] or ('DEADLINE_EXCEEDED' if view['status']=='expired' else 'SUBMISSION_UNKNOWN')
                    if code not in {item.value for item in ErrorCode}: code='PROVIDER_REJECTED'
                    if code == 'SUBMISSION_UNKNOWN':
                        return failure(code, '供应商可能已受理并产生费用',
                                       '使用原任务 ID 或幂等键查询；未经用户授权不得另行提交',
                                       data=view, task_id=view['task_id'], phase='submission', reason='outcome_unknown')
                    return failure(code,'任务未成功完成','查询任务状态',data=view,task_id=view['task_id'])
                result=success(view, self._size_warnings(view))
                if request.output_format=='gif' and view['images']:
                    width,height=view['images'][0]['width'],view['images'][0]['height']
                    mismatch=(request.width is not None and (width,height)!=(request.width,request.height))
                    if request.size and ':' in request.size:
                        a,b=map(int,request.size.split(':'));mismatch=mismatch or width*b != height*a
                    if mismatch: result['warnings'].append('GIF 实际尺寸或比例与请求不同，已按用户选择保留实际尺寸')
                return await self._add_preview(result,view['task_id'])
            if name == 'generate_batch':
                requests=[GenerationRequest.model_validate(item) for item in args['requests']]
                batch, rows=await self.generation.generate_batch(requests)
                records=await self.worker.run(lambda db: db.execute('SELECT input_index,reused FROM batch_items WHERE batch_id=? ORDER BY input_index',(batch,)).fetchall())
                views=[await self._task(row) for row in rows]
                unresolved={'queued','submitting','retry_wait','materializing','unknown','recovery_pending'}
                result=success({'batch_id':batch,'items':[{'input_index':r['input_index'],'reused':bool(r['reused']),'task':v} for r,v in zip(records,views)],
                    'succeeded_count':sum(v['status']=='succeeded' for v in views),
                    'unresolved_count':sum(v['status'] in unresolved for v in views),
                    'failed_count':sum(v['status'] not in unresolved|{'succeeded'} for v in views)}, self._size_warnings(*views))
                first=next((v for v in views if v['status']=='succeeded'),None)
                return await self._add_preview(result,first['task_id']) if first else result
            if name == 'get_task':
                field='task_id' if args.get('task_id') else 'idempotency_key'
                row=await self.worker.fetchone('SELECT * FROM tasks WHERE '+field+'=?',(args[field],))
                if row is None: raise KeyError('task')
                view = await self._task(row)
                return success(view, self._size_warnings(view))
            if name == 'list_tasks':
                filters=dict(args); filters['created_from']=millis(filters.get('created_from'));filters['created_to']=millis(filters.get('created_to'))
                rows,cursor=await self.worker.run(lambda db:list_tasks(db,**filters))
                return success({'items':[await self._task(row) for row in rows], 'next_cursor':cursor})
            if name == 'save_prompt_template':
                value=SaveTemplateInput.model_validate(args)
                row=await self.worker.run(save_template,value,time.time_ns()//1_000_000)
                return success(self._template(row))
            if name == 'get_prompt_template':
                return success(self._template(await self.worker.run(get_template,args['code'])))
            if name == 'list_prompt_templates':
                rows,cursor=await self.worker.run(lambda db:list_templates(db,**args))
                return success({'items':[self._template(row) for row in rows],'next_cursor':cursor})
            if name == 'render_prompt_template':
                row=await self.worker.run(get_template,args['code'])
                if row is None: raise KeyError('template')
                return success(render_template(row,args['variables']))
            if self.recovery is not None:
                if name == '__prepare_recovery__':
                    return await self._prepare_recovery(args)
                if name == '__recovery_plan__':
                    details, _ = self._recovery_plan(args['plan_id'])
                    return success(details)
                if name == '__execute_recovery__':
                    return await self._execute_recovery(args['plan_id'])
                if name == 'inspect_closed_artifact':
                    try:
                        return success(await self.recovery.closed_candidate(args['task_id'], args['image_index']))
                    except (StateConflict, OSError, ValueError):
                        return failure('ARTIFACT_UNAVAILABLE', '已结案原件缺失、已清理或未通过归属及完整性校验',
                                       '查看任务历史及已保存的导出副本', task_id=args['task_id'])
            if name in ('recover_task','accept_gif_size','get_image'):
                if self.recovery is None: return failure('CONFIG_ERROR','恢复功能尚未接入','完成服务组装')
                return await self._recovery_call(name,args)
            return failure('INVALID_ARGUMENT','未知工具','检查工具名称')
        except IdempotencyConflict:
            return failure('IDEMPOTENCY_CONFLICT','幂等键冲突','使用原请求或新键')
        except TemplateConflict:
            return failure('TEMPLATE_VERSION_CONFLICT','模板版本冲突','读取当前版本')
        except QueueFull:
            return failure('QUEUE_FULL','任务队列已满','等待或处理未完成任务')
        except StateConflict:
            return failure('STATE_CONFLICT','任务状态已改变','重新查询任务')
        except KeyError:
            return failure('NOT_FOUND','记录不存在','检查标识')
        except ValueError:
            return failure('INVALID_ARGUMENT','参数不合法','检查参数与模板')
