"""Template storage and literal, non-executable placeholder rendering."""
import base64
import hashlib
import json
import re
import sqlite3
from zhenzhen_gptimage.generation.contracts import SaveTemplateInput, TemplateVariable

_PLACEHOLDER = re.compile(r'\{\{([A-Za-z0-9_-]{1,64})\}\}')

class TemplateConflict(ValueError): pass

def _validate_content(content, variables):
    placeholders = set(_PLACEHOLDER.findall(content))
    remainder = _PLACEHOLDER.sub('', content)
    if '{{' in remainder or '}}' in remainder or placeholders != {v.name for v in variables}:
        raise ValueError('placeholder definitions do not match template')

def save_template(db: sqlite3.Connection, request: SaveTemplateInput, now_ms: int):
    _validate_content(request.content, request.variables)
    variables = json.dumps([v.model_dump(exclude_none=True) for v in request.variables], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT * FROM prompt_templates WHERE code=?', (request.code,)).fetchone()
        if row is None:
            if request.expected_version is not None:
                raise TemplateConflict('template does not exist')
            db.execute('INSERT INTO prompt_templates VALUES (?,?,?,?,?,?)', (request.code, 1, request.content, variables, now_ms, now_ms))
        else:
            if request.expected_version != row['version']:
                raise TemplateConflict('template version conflict')
            if row['content'] != request.content or row['variables_json'] != variables:
                db.execute('UPDATE prompt_templates SET content=?,variables_json=?,version=version+1,updated_at=? WHERE code=? AND version=?', (request.content, variables, now_ms, request.code, request.expected_version))
        result = dict(db.execute('SELECT * FROM prompt_templates WHERE code=?', (request.code,)).fetchone())
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise

def get_template(db, code):
    row = db.execute('SELECT * FROM prompt_templates WHERE code=?', (code,)).fetchone()
    return dict(row) if row else None

def render_template(row, values: dict[str,str]):
    variables = [TemplateVariable.model_validate(v) for v in json.loads(row['variables_json'])]
    _validate_content(row['content'], variables)
    names = {v.name for v in variables}
    if set(values) - names:
        raise ValueError('unknown template variable')
    replacements = {}
    for item in variables:
        value = values.get(item.name, item.default)
        if value is None:
            raise ValueError('missing template variable')
        replacements[item.name] = value
    result = _PLACEHOLDER.sub(lambda match: replacements[match.group(1)], row['content'])
    if len(result.encode('utf-8')) > 32768:
        raise ValueError('rendered prompt exceeds limit')
    return {'code': row['code'], 'version': row['version'], 'prompt': result}

def list_templates(db, *, query=None, limit=20, cursor=None):
    if not 1 <= limit <= 100: raise ValueError('invalid limit')
    fingerprint = hashlib.sha256(json.dumps([query],ensure_ascii=False).encode()).hexdigest()
    after = ''
    if cursor:
        try:
            parsed = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if parsed['filter'] != fingerprint or not isinstance(parsed['after'], str): raise ValueError()
            after = parsed['after']
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise ValueError('invalid cursor') from exc
    q = query or ''
    rows = db.execute('SELECT * FROM prompt_templates WHERE code>? AND (instr(code,?)>0 OR instr(content,?)>0) ORDER BY code LIMIT ?', (after, q, q, limit+1)).fetchall()
    page = [dict(row) for row in rows[:limit]]
    next_cursor = base64.urlsafe_b64encode(json.dumps({'filter':fingerprint,'after':page[-1]['code']}).encode()).decode() if len(rows)>limit else None
    return page, next_cursor
