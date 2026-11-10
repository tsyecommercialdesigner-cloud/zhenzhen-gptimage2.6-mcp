"""Business adapter for the MCP surface; no transport-specific state."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import time
from zhenzhen_gptimage.generation.models import GenerationRequest
from zhenzhen_gptimage.generation.contracts import SaveTemplateInput, ErrorCode
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
def failure(code, message, action, *, data=None, task_id=None):
    error={'code':code,'message':message,'next_action':action,'retryable':False}
    if task_id is not None: error['task_id']=task_id
    return {'ok':False,'data':data,'warnings':[],'error':error}

class ServiceBackend:
    def __init__(self, worker, generation, recovery=None):
        self.worker, self.generation, self.recovery = worker, generation, recovery

    async def _task(self, row):
        row = dict(row)
        images = await self.worker.run(lambda db: [dict(r) for r in db.execute('SELECT * FROM image_artifacts WHERE task_id=? ORDER BY image_index',(row['task_id'],))])
        if row['status']=='recovery_pending' and not images:
            images=await self.worker.run(lambda db:[dict(r) for r in db.execute('SELECT * FROM pending_image_artifacts WHERE task_id=? ORDER BY image_index',(row['task_id'],))])
        for image in images:
            image.pop('revised_prompt',None); image.pop('created_at',None)
            pending_metadata=image.pop('metadata_json',None)
            meta=await self.worker.fetchone('SELECT metadata_json FROM image_format_metadata WHERE task_id=? AND image_index=?',(row['task_id'],image['image_index']))
            if pending_metadata is not None or meta is not None:
                image['metadata']=json.loads(pending_metadata if pending_metadata is not None else meta['metadata_json'])
            if self.recovery is not None:
                if pending_metadata is not None:
                    from zhenzhen_gptimage.artifacts.recovery import _read_image
                    import asyncio
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
        if row['status']=='recovery_pending' and images and images[0].get('mime_type')=='image/gif':
            actions = actions + ['accept_gif_size']
        return {'task_id':row['task_id'],'batch_id':row['batch_id'], 'idempotency_key':row['idempotency_key'],
                'status':row['status'],'resolved_model':row['resolved_model'],'channel':row['channel'],
                'width':row['width'],'height':row['height'],'created_at':iso(row['created_at']),
                'deadline_at':iso(row['deadline_at']),'attempt_count':row['attempt_count'],
                'images':images,'error_category':row['error_category'],'allowed_actions':actions,
                'remote_task': dict(remote) if remote is not None else None}

    @staticmethod
    def _template(row):
        if row is None: raise KeyError('template')
        out=dict(row); out['variables']=json.loads(out.pop('variables_json'))
        out['created_at']=iso(out['created_at']);out['updated_at']=iso(out['updated_at'])
        return out

    async def _recovery_call(self, name, args):
        if name == 'recover_task':
            row=await self.recovery.recover(args['task_id'])
            result=success(await self._task(row))
            return await self._add_preview(result,args['task_id']) if row['status']=='succeeded' else result
        if name == 'close_task':
            row,_=await self.recovery.close(args['task_id'],args['expected_status'],args['reason'])
            return success(await self._task(row))
        if name == 'accept_gif_size':
            row=await self.recovery.accept_gif_size(args['task_id'],args['sha256'],args['width'],args['height'])
            return await self._add_preview(success(await self._task(row)),args['task_id'])
        row, preview=await self.recovery.image(args['task_id'],args.get('image_index',0),args.get('include_preview',True))
        row=dict(row);row.pop('created_at',None);row.pop('revised_prompt',None)
        meta=await self.worker.fetchone('SELECT metadata_json FROM image_format_metadata WHERE task_id=? AND image_index=?',(args['task_id'],args.get('image_index',0)))
        if meta is not None: row['metadata']=json.loads(meta['metadata_json'])
        if not row['available']:
            return failure('ARTIFACT_UNAVAILABLE','图片文件不可用','检查本地文件',data=row,task_id=args['task_id'])
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
                if view['status'] != 'succeeded':
                    code=view['error_category'] or ('DEADLINE_EXCEEDED' if view['status']=='expired' else 'SUBMISSION_UNKNOWN')
                    if code not in {item.value for item in ErrorCode}: code='PROVIDER_REJECTED'
                    return failure(code,'任务未成功完成','查询任务状态',data=view,task_id=view['task_id'])
                result=success(view)
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
                    'failed_count':sum(v['status'] not in unresolved|{'succeeded'} for v in views)})
                first=next((v for v in views if v['status']=='succeeded'),None)
                return await self._add_preview(result,first['task_id']) if first else result
            if name == 'get_task':
                field='task_id' if args.get('task_id') else 'idempotency_key'
                row=await self.worker.fetchone('SELECT * FROM tasks WHERE '+field+'=?',(args[field],))
                if row is None: raise KeyError('task')
                return success(await self._task(row))
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
            if name in ('recover_task','close_task','accept_gif_size','get_image'):
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
