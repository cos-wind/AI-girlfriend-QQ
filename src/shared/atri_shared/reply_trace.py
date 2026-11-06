"""Best-effort reply observation: task-local spans and bounded async storage.

Never collect prompts, message bodies, raw tool args or exception messages.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, closing
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import inspect
import json
from pathlib import Path
import re
import sqlite3
from threading import Condition, Lock, Thread
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import uuid

_current = ContextVar('atri_reply_trace', default=None)
_parent = ContextVar('atri_reply_span', default='')
_store = None
_store_lock = Lock()
MAX_SPANS = 240


def safe_text(value, limit=160):
    text = ' '.join(str(value or '').split())
    text = re.sub(r'(?i)(?:bearer\s+|sk-)[\w.\-]+', '[已隐藏]', text)
    text = re.sub(r'(?i)(token|api[_-]?key|password|secret)\s*[=:：]\s*[^\s,;]+', r'\1=[已隐藏]', text)
    return text[:limit]


def safe_url(value):
    try:
        url = urlsplit(str(value))
        if url.scheme not in {'https', 'http'} or not url.hostname:
            return ''
        return urlunsplit((url.scheme, url.hostname, url.path[:240], '', ''))
    except (ValueError, TypeError):
        return ''


def _fields(fields):
    result = {}
    for key in ('model', 'tool', 'query', 'provider', 'code', 'error_type', 'note', 'count', 'action', 'status'):
        if key in fields:
            result[key] = safe_text(fields[key])
    if 'sources' in fields:
        result['sources'] = list(dict.fromkeys(filter(None, (safe_url(u) for u in fields['sources'][:8]))))
    return result


@dataclass(frozen=True)
class TurnTraceEvent:
    stage: str
    elapsed_ms: int
    fields: dict[str, Any] = field(default_factory=dict)


class TurnTrace:
    """Existing in-memory turn events, optionally published to an outer sink."""
    def __init__(self, turn_id: str, *, sink=None, route='', conversation='', summary=''):
        self.turn_id = turn_id
        self._started = time.perf_counter()
        self.started_at = time.time()
        self._events, self.spans = [], []
        self.status, self.ended_ms = 'running', None
        self.route, self.conversation, self.summary = route, conversation, summary
        self._sink, self._lock = sink, Lock()

    def elapsed(self):
        return round((time.perf_counter() - self._started) * 1000)

    def record(self, stage, **fields):
        event = TurnTraceEvent(stage, self.elapsed(), dict(fields))
        with self._lock:
            if len(self._events) < MAX_SPANS:
                self._events.append(event)
        return event

    def snapshot(self):
        with self._lock:
            return tuple(self._events)

    def publish(self):
        if self._sink:
            try:
                with self._lock:
                    body = dict(trace_id=self.turn_id, route=self.route, conversation=self.conversation,
                        summary=self.summary, started_at=self.started_at, updated_at=time.time(),
                        elapsed_ms=self.ended_ms if self.ended_ms is not None else self.elapsed(),
                        status=self.status, spans=[dict(s, fields=dict(s['fields'])) for s in self.spans])
                self._sink.publish(body)
            except Exception:
                pass


_SKIPPED_KEEP = 60    # 未触发回复：每条入站消息一条，只留够看最近一小时的判断情况
_REPLIED_KEEP = 200   # 真实回复：这些才是有分析价值的轮次，不能被噪声挤掉


class TraceStore:
    """Coalesced snapshots: <=128 pending turns; skipped and replied turns are retained separately."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self._condition = Condition()
        self._pending, self._busy, self._closed = {}, False, False
        self._thread = Thread(target=self._run, name='atri-reply-traces', daemon=True)
        self._thread.start()

    def publish(self, body):
        with self._condition:
            if self._closed:
                return
            if len(self._pending) >= 128:
                self._pending.pop(next(iter(self._pending)))
            self._pending[body['trace_id']] = body
            self._condition.notify()

    def _write(self, bodies):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=.5)) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS traces (id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT UNIQUE, updated REAL, body TEXT)')
            # 旧库没有 status 列：补上后把已有记录的状态回填，否则老噪声会被当成真实回复永久保留。
            if 'status' not in {row[1] for row in db.execute('PRAGMA table_info(traces)')}:
                db.execute('ALTER TABLE traces ADD COLUMN status TEXT')
                for row_id, raw in db.execute('SELECT id, body FROM traces WHERE status IS NULL').fetchall():
                    try:
                        previous = json.loads(raw).get('status')
                    except (ValueError, TypeError):
                        continue
                    db.execute('UPDATE traces SET status=? WHERE id=?', (previous, row_id))
            db.executemany('INSERT OR REPLACE INTO traces(trace_id,updated,body,status) VALUES(?,?,?,?)',
                [(b['trace_id'], b['updated_at'], json.dumps(b, ensure_ascii=False), b.get('status')) for b in bodies])
            db.execute('DELETE FROM traces WHERE updated < ?', (time.time()-86400,))
            # 两类分开裁剪。混在一起按 id 排序时，未触发的私聊消息会以数量优势
            # 把真正产生回复的轮次挤出上限（实测 200 条里 197 条是未触发）。
            for keep, match in ((_SKIPPED_KEEP, "status='skipped'"), (_REPLIED_KEEP, "COALESCE(status,'')<>'skipped'")):
                db.execute(f'DELETE FROM traces WHERE {match} AND id NOT IN '
                           f'(SELECT id FROM traces WHERE {match} ORDER BY id DESC LIMIT ?)', (keep,))

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._closed)
                if self._closed and not self._pending:
                    return
                self._condition.wait(timeout=.05)
                bodies = list(self._pending.values())
                self._pending.clear()
                self._busy = True
            try:
                self._write(bodies)
            except Exception:
                pass
            finally:
                with self._condition:
                    self._busy = False
                    self._condition.notify_all()

    def flush(self, timeout=3):
        with self._condition:
            return self._condition.wait_for(lambda: not self._pending and not self._busy, timeout)

    def close(self):
        self.flush()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=3)


def trace_path():
    from .runtime.paths import DATA_DIR
    return DATA_DIR / 'observability' / 'reply-traces.sqlite3'


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            _store = TraceStore(trace_path())
        return _store


def read_traces(cursor=0, *, path=None):
    path = Path(path) if path is not None else trace_path()
    if not path.exists():
        return dict(ok=True, items=[], cursor=cursor)
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.1)) as db:
            rows = db.execute('SELECT id, body FROM traces WHERE id > ? AND updated > ? ORDER BY id DESC LIMIT 200',
                              (cursor, time.time()-86400)).fetchall()
        items = [json.loads(body) for _, body in rows]
        for item in items:
            if item['status'] == 'running' and time.time()-item['updated_at'] > 600:
                item['status'] = 'interrupted'
        return dict(ok=True, items=items, cursor=max([cursor]+[row[0] for row in rows]))
    except Exception:
        return dict(ok=False, error='暂时无法读取链路记录，请稍后重试')


@contextmanager
def reply_turn(route, conversation='', summary='', *, sink=None, queued_at=None):
    try:
        trace = TurnTrace(uuid.uuid4().hex, sink=sink if sink is not None else get_store(),
                          route=route, conversation=safe_text(conversation), summary=safe_text(summary))
    except Exception:
        yield None
        return
    if isinstance(queued_at, (float, int)) and 0 <= time.perf_counter()-queued_at < 86400:
        waiting = time.perf_counter()-queued_at
        trace._started -= waiting
        trace.started_at -= waiting
        trace.spans.append(dict(id=uuid.uuid4().hex[:12], parent='', stage='queue_wait',
            start_ms=0, end_ms=round(waiting*1000), status='done', fields={'note':'从入队到出队，含消息合并等待；出队后补记'}))
    token, parent_token = _current.set(trace), _parent.set('')
    trace.publish()
    try:
        yield trace
    except BaseException as exc:
        trace.status = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed'
        raise
    finally:
        if trace.status == 'running':
            trace.status = 'done'
        trace.ended_ms = trace.elapsed()
        trace.publish()
        _parent.reset(parent_token)
        _current.reset(token)


class Span:
    def __init__(self, trace=None, row=None):
        self.trace, self.row = trace, row

    def update(self, **fields):
        try:
            if self.row:
                with self.trace._lock:
                    self.row['fields'].update(_fields(fields))
                self.trace.publish()
        except Exception:
            pass

    def fail(self, code='failed'):
        if self.row:
            self.row['status'] = 'failed'
            self.update(code=code)

    def result(self, value):
        # Some existing APIs return a failure result instead of raising.
        try:
            if getattr(value, 'ok', None) is False:
                self.fail('result_failed')
        except Exception:
            pass
        return value


@contextmanager
def span(stage, **fields):
    trace, row = _current.get(), None
    try:
        if trace and trace.status == 'running' and len(trace.spans) < MAX_SPANS:
            row = dict(id=uuid.uuid4().hex[:12], parent=_parent.get(), stage=stage,
                       start_ms=trace.elapsed(), end_ms=None, status='running', fields=_fields(fields))
            with trace._lock:
                trace.spans.append(row)
            trace.publish()
    except Exception:
        row = None
    token = _parent.set(row['id'] if row else _parent.get())
    handle = Span(trace, row)
    try:
        yield handle
    except BaseException as exc:
        if row:
            row['status'] = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed'
            handle.update(error_type=type(exc).__name__)
        raise
    finally:
        if row:
            row['end_ms'] = trace.elapsed()
            if row['status'] == 'running':
                row['status'] = 'done'
            trace.publish()
        _parent.reset(token)


def traced(stage):
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def run(*args, **kwargs):
                with span(stage) as observed:
                    return observed.result(await fn(*args, **kwargs))
        else:
            @wraps(fn)
            def run(*args, **kwargs):
                with span(stage) as observed:
                    return observed.result(fn(*args, **kwargs))
        return run
    return decorate


def fail_current(code='failed'):
    trace = _current.get()
    if trace:
        trace.status = 'failed'
        trace.publish()


def skip_current():
    trace = _current.get()
    if trace:
        trace.status = 'skipped'


def tool_fields(name, arguments, content=''):
    fields = dict(tool=name)
    if name == 'search_web':
        fields['query'] = arguments.get('query', '')
    if name in {'read_webpage', 'fetch_webpage', 'open_web_page'}:
        fields['sources'] = [arguments.get('url', '')]
    if content:
        fields['count'] = len(content)
        fields['sources'] = re.findall(r'https?://[^\s<>\]）)]+', str(content))[:8]
    return fields


def observed_tool(name):
    def decorate(fn):
        @wraps(fn)
        async def run(arguments=None, config=None):
            with span('search' if name == 'search_web' else 'webpage',
                      **tool_fields(name, arguments or {})) as observed:
                content = await fn(arguments, config)
                observed.update(**tool_fields(name, arguments or {}, content))
                if str(content).startswith(('搜索失败', '搜索未执行', '网页读取失败')):
                    observed.fail('unavailable')
                return content
        return run
    return decorate
