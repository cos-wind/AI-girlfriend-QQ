"""Canonical knowledge, revision-bound evidence and reversible consolidation.

Extraction fragments remain immutable evidence, never synthetic corroboration.
All mutations use SQLite transactions and stable identities. No model is called
on a read path. Source revision joins invalidate assertions immediately.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid

from .covers import cover_for
from .store import RevisionConflict

_migration_lock = threading.Lock()


def backup_legacy(store):
    """Online SQLite backup before the first nonempty legacy migration, including WAL."""
    store.ensure_schema()
    with _migration_lock, closing(store._connect()) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_entities'").fetchone():
            return
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_cards'").fetchone() or not conn.execute('SELECT 1 FROM knowledge_cards LIMIT 1').fetchone():
            return
        destination = store.path.with_name(store.path.stem + '.before-entities-v1.sqlite3')
        try:
            with destination.open('xb'):
                pass
        except FileExistsError:
            return
        try:
            with closing(sqlite3.connect(destination)) as backup:
                conn.backup(backup)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(data, source_id):
    # Preserve punctuation, numbers, case, minus signs, code and formula conditions.
    keys = ('domain', 'kind', 'summary', 'points', 'format', 'question', 'answer', 'details', 'charts')
    value = {k: data.get(k, [] if k in {'points', 'charts'} else '') for k in keys}
    if data.get('kind') != 'knowledge':
        value['event_source'] = source_id
    return hashlib.sha256(dump(value).encode()).hexdigest()


def search_tokens(text):
    """FTS terms for Chinese and code names without destroying the stored text."""
    tokens = []
    for word in re.findall(r'[\u4e00-\u9fff]+|[A-Za-z0-9_]+', text.lower()):
        if word.isascii():
            tokens.append(word)
        else:
            tokens.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
    return list(dict.fromkeys(tokens))


class KnowledgeEntities:
    def __init__(self, store):
        self.store = store
        backup_legacy(store)
        with store.transaction() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS knowledge_entities (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    data TEXT NOT NULL DEFAULT '{}', member_key TEXT NOT NULL DEFAULT '',
                    hidden INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 2147483647,
                    locked INTEGER NOT NULL DEFAULT 0, redirect TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS knowledge_entities_scope ON knowledge_entities(scope,redirect);
                CREATE TABLE IF NOT EXISTS knowledge_entity_members (
                    card_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, scope TEXT NOT NULL,
                    source_id TEXT NOT NULL, source_revision INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS knowledge_member_entity ON knowledge_entity_members(entity_id);
                CREATE INDEX IF NOT EXISTS knowledge_member_source ON knowledge_entity_members(source_id);
                CREATE INDEX IF NOT EXISTS knowledge_member_fingerprint ON knowledge_entity_members(scope,fingerprint);
                CREATE TABLE IF NOT EXISTS knowledge_member_relations (
                    card_id TEXT PRIMARY KEY, relation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS knowledge_entity_dirty (id TEXT PRIMARY KEY);
                CREATE TRIGGER IF NOT EXISTS knowledge_member_added AFTER INSERT ON knowledge_entity_members BEGIN
                    INSERT OR IGNORE INTO knowledge_entity_dirty VALUES(new.entity_id); END;
                CREATE TRIGGER IF NOT EXISTS knowledge_member_changed AFTER UPDATE ON knowledge_entity_members BEGIN
                    INSERT OR IGNORE INTO knowledge_entity_dirty VALUES(old.entity_id);
                    INSERT OR IGNORE INTO knowledge_entity_dirty VALUES(new.entity_id); END;
                CREATE TRIGGER IF NOT EXISTS knowledge_source_changed AFTER UPDATE OF revision ON knowledge_sources BEGIN
                    INSERT OR IGNORE INTO knowledge_entity_dirty SELECT entity_id FROM knowledge_entity_members WHERE source_id=new.id; END;
                CREATE TRIGGER IF NOT EXISTS knowledge_source_removed AFTER DELETE ON knowledge_sources BEGIN
                    INSERT OR IGNORE INTO knowledge_entity_dirty SELECT entity_id FROM knowledge_entity_members WHERE source_id=old.id; END;
                CREATE TRIGGER IF NOT EXISTS knowledge_context_changed AFTER UPDATE OF revision ON knowledge_sources BEGIN
                    INSERT OR IGNORE INTO knowledge_entity_dirty SELECT m.entity_id FROM knowledge_entity_members m
                    JOIN knowledge_card_contexts x ON x.card_id=m.card_id WHERE x.source_id=new.id; END;
                CREATE TRIGGER IF NOT EXISTS knowledge_context_removed AFTER DELETE ON knowledge_sources BEGIN
                    INSERT OR IGNORE INTO knowledge_entity_dirty SELECT m.entity_id FROM knowledge_entity_members m
                    JOIN knowledge_card_contexts x ON x.card_id=m.card_id WHERE x.source_id=old.id; END;
                CREATE TABLE IF NOT EXISTS knowledge_entity_revisions (
                    entity_id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL,
                    member_key TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(entity_id,revision));
                CREATE TABLE IF NOT EXISTS knowledge_entity_covers (
                    entity_id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS knowledge_entity_locations (
                    entity_id TEXT PRIMARY KEY,domain TEXT NOT NULL,topic TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_entity_fts USING fts5(
                    entity_id UNINDEXED, scope UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS knowledge_merge_history (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, target TEXT NOT NULL, incoming TEXT NOT NULL,
                    relation TEXT NOT NULL, reason TEXT NOT NULL, before_state TEXT NOT NULL,
                    after_state TEXT NOT NULL, created REAL NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS knowledge_separations (
                    scope TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL, PRIMARY KEY(scope,a,b));
                CREATE TABLE IF NOT EXISTS knowledge_consolidation_jobs (
                    entity_id TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    token TEXT NOT NULL DEFAULT '', lease REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
                    started REAL NOT NULL DEFAULT 0, finished REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(entity_id,revision));
                CREATE TABLE IF NOT EXISTS knowledge_relations (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
                    a_revision INTEGER NOT NULL, b_revision INTEGER NOT NULL,
                    relation TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    created REAL NOT NULL, UNIQUE(scope,a,b,a_revision,b_revision));
            ''')

    @staticmethod
    def members(conn, scope, entity_id, day=''):
        return conn.execute('''SELECT m.*,COALESCE(mr.relation,'complement') AS relation,s.day,s.kind AS source_kind,s.title AS source_title,
            s.occurred_at,r.coverage,s.metadata FROM knowledge_entity_members m
            JOIN knowledge_sources s ON s.id=m.source_id AND s.revision=m.source_revision
            JOIN knowledge_revisions r ON r.source_id=s.id AND r.revision=s.revision
            LEFT JOIN knowledge_member_relations mr ON mr.card_id=m.card_id
            WHERE m.scope=? AND s.scope=? AND m.entity_id=? AND (?='' OR s.day=?)
            AND NOT EXISTS(SELECT 1 FROM knowledge_card_contexts x LEFT JOIN knowledge_sources q
                ON q.id=x.source_id AND q.revision=x.revision AND q.scope=m.scope
                WHERE x.card_id=m.card_id AND q.id IS NULL)
            ORDER BY s.occurred_at,m.card_id''', (scope, scope, entity_id, day, day)).fetchall()

    @staticmethod
    def compose(members):
        if not members:
            return {}
        # A user's authored body is authoritative; evidence remains separately linked.
        manuals = [m for m in members if json.loads(m['metadata']).get('manual_card')]
        ordered = sorted(members, key=lambda m: m['relation'] == 'equivalent')
        records = [json.loads(m['data']) for m in ordered]
        authority = next((m for m in manuals if m['relation'] == 'authoritative'), manuals[-1] if manuals else None)
        data = dict(json.loads(authority['data']) if authority else records[0])
        if not manuals:
            summaries = list(dict.fromkeys(r['summary'] for i, r in enumerate(records)
                                           if i == 0 or ordered[i]['relation'] != 'equivalent'))
            points = list(dict.fromkeys(p for r in records for p in r.get('points', [])))
            data['points'] = points
            data['terms'] = list(dict.fromkeys(t for r in records for t in r.get('terms', [])))[:20]
            # Lossless composition: new facts stay tied to their original fragment.
            data['summary'] = '\n\n'.join(summaries)
            details = list(dict.fromkeys(r.get('details', '') for r in records if r.get('details')))
            data['details'] = '\n\n---\n\n'.join(details)
            charts = []
            for r in records:
                for chart in r.get('charts', []):
                    if chart not in charts:
                        charts.append(chart)
            data['charts'] = charts
            if len(summaries) > 1:
                # Rebuild an honest full cover instead of retaining an outdated short one.
                data.pop('cover', None)
        return data

    def rebuild(self, conn, scope, entity_id, reason='evidence', *, force=False):
        row = conn.execute('SELECT * FROM knowledge_entities WHERE scope=? AND id=?', (scope, entity_id)).fetchone()
        members = self.members(conn, scope, entity_id)
        member_key = hashlib.sha256(dump([(m['card_id'], m['source_revision'], m['data']) for m in members]).encode()).hexdigest()
        if not force and row['member_key'] == member_key:
            conn.execute('DELETE FROM knowledge_entity_dirty WHERE id=?', (entity_id,))
            return
        data = self.compose(members)
        revision = row['revision'] + 1
        if data:
            self.locate(conn, entity_id, data)
            override = conn.execute('SELECT data FROM knowledge_entity_covers WHERE entity_id=?', (entity_id,)).fetchone()
            if override:
                data['cover'] = json.loads(override[0])
            data['cover'] = cover_for(data, revision=revision, locked=bool(data.get('cover', {}).get('locked')))
        conn.execute('UPDATE knowledge_entities SET revision=?,data=?,member_key=?,updated=? WHERE id=?',
                     (revision, dump(data), member_key, time.time(), entity_id))
        conn.execute('INSERT INTO knowledge_entity_revisions VALUES(?,?,?,?,?,?)',
                     (entity_id, revision, dump(data), member_key, reason, time.time()))
        conn.execute('DELETE FROM knowledge_entity_fts WHERE entity_id=?', (entity_id,))
        conn.execute('DELETE FROM knowledge_entity_dirty WHERE id=?', (entity_id,))
        if data and not row['redirect'] and not row['hidden']:
            searchable = ' '.join(str(data.get(k, '')) for k in ('title', 'topic', 'summary', 'terms', 'details'))
            conn.execute('INSERT INTO knowledge_entity_fts VALUES(?,?,?)',
                         (entity_id, scope, ' '.join(search_tokens(searchable))))
            if data['kind'] == 'knowledge':
                conn.execute('INSERT OR IGNORE INTO knowledge_consolidation_jobs(entity_id,revision) VALUES(?,?)',
                             (entity_id, revision))

    def sync(self, scope):
        """Additive legacy migration and incremental reconciliation; no original writes."""
        with self.store.transaction() as conn:
            rows = conn.execute('''SELECT c.*,COALESCE(p.hidden,0) AS hidden,
                COALESCE(p.position,2147483647) AS position,COALESCE(p.revision,0) AS edit_revision,s.metadata
                FROM knowledge_cards c JOIN knowledge_sources s ON s.id=c.source_id AND s.revision=c.revision
                LEFT JOIN knowledge_card_preferences p ON p.scope=s.scope AND p.signature=c.signature
                LEFT JOIN knowledge_entity_members m ON m.card_id=c.id
                WHERE s.scope=? AND (m.card_id IS NULL OR m.source_revision<>c.revision OR m.data<>c.data)
                ORDER BY s.occurred_at,c.id''', (scope,)).fetchall()
            for row in rows:
                data = json.loads(row['data'])
                fp = ('manual:' + row['source_id']) if json.loads(row['metadata']).get('manual_card') else fingerprint(data, row['source_id'])
                old = conn.execute('SELECT entity_id FROM knowledge_entity_members WHERE card_id=?', (row['id'],)).fetchone()
                match = conn.execute('''SELECT e.id FROM knowledge_entity_members m JOIN knowledge_entities e ON e.id=m.entity_id
                    WHERE m.scope=? AND m.fingerprint=? AND e.redirect='' ORDER BY e.created,e.id LIMIT 1''', (scope, fp)).fetchone()
                entity_id = old['entity_id'] if old else match['id'] if match else row['id']
                conn.execute('''INSERT OR IGNORE INTO knowledge_entities(id,scope,hidden,position,locked,created,updated)
                    VALUES(?,?,?,?,?,?,?)''', (entity_id, scope, row['hidden'], row['position'],
                        int(bool(json.loads(row['metadata']).get('manual_card'))), time.time(), time.time()))
                conn.execute('''INSERT OR REPLACE INTO knowledge_entity_members VALUES(?,?,?,?,?,?,?)''',
                             (row['id'], entity_id, scope, row['source_id'], row['revision'], fp, row['data']))
            # Source changes invalidate the current materialized view even without extraction.
            for row in conn.execute("SELECT e.id FROM knowledge_entities e JOIN knowledge_entity_dirty d ON d.id=e.id WHERE e.scope=? AND e.redirect=''", (scope,)).fetchall():
                self.rebuild(conn, scope, row['id'])

    @staticmethod
    def locate(conn, entity_id, data):
        location = conn.execute('SELECT domain,topic FROM knowledge_entity_locations WHERE entity_id=?', (entity_id,)).fetchone()
        if location:
            data.update(domain=location['domain'], topic=location['topic'])
        return data

    @staticmethod
    def resolve(conn, scope, entity_id, revision=None, *, visible=True):
        if not isinstance(entity_id, str) or not entity_id or len(entity_id) > 100:
            raise ValueError('知识主卡标识无效')
        seen = set()
        while entity_id not in seen:
            seen.add(entity_id)
            row = conn.execute('SELECT * FROM knowledge_entities WHERE scope=? AND id=?', (scope, entity_id)).fetchone()
            if not row:
                alias = conn.execute('SELECT entity_id FROM knowledge_entity_members WHERE scope=? AND card_id=?', (scope, entity_id)).fetchone()
                if alias:
                    entity_id = alias[0]
                    continue
                break
            if row['redirect']:
                entity_id = row['redirect']
                continue
            if visible and (row['hidden'] or not json.loads(row['data'])):
                break
            if revision is not None and (type(revision) is not int or revision != row['revision']):
                raise RevisionConflict('知识已更新，请刷新后再操作')
            return row
        raise ValueError('卡片已删除、来源已失效或不属于当前知识库')

    def card(self, conn, row, day=''):
        members = self.members(conn, row['scope'], row['id'], day)
        if not members:
            return None
        data = self.compose(members) if day else json.loads(row['data'])
        self.locate(conn, row['id'], data)
        data['cover'] = cover_for(data, revision=row['revision'], locked=bool(data.get('cover', {}).get('locked')))
        evidence, seen = [], set()
        for m in reversed(members):
            key = (m['source_id'], m['source_revision'])
            if key in seen:
                continue
            seen.add(key)
            if len(evidence) < 20:
                evidence.append({'id': m['source_id'], 'revision': m['source_revision'], 'day': m['day'],
                                 'role': m['source_kind'], 'title': m['source_title'], 'coverage': m['coverage'],
                                 'quote': json.loads(m['data']).get('quote', '')})
            for context in self.context_evidence(conn, row['scope'], m['card_id']):
                key = (context['id'], context['revision'])
                if key not in seen:
                    seen.add(key)
                    if len(evidence) < 20:
                        evidence.append(context)
        data.update(id=row['id'], edit_revision=row['revision'], day=day or members[-1]['day'],
                    evidence=evidence, evidence_count=len(seen), locked=bool(row['locked']),
                    first_day=members[0]['day'], last_day=members[-1]['day'],
                    fragment_count=len(members), historical=bool(day))
        # Every claim names its revision-bound original, also used by future RAG.
        data['claims'] = [{'member_id': m['card_id'], 'source_id': m['source_id'],
                           'revision': m['source_revision'], 'summary': json.loads(m['data'])['summary']}
                          for m in members[:100]]
        return data

    @staticmethod
    def context_evidence(conn, scope, card_id):
        return [dict(r) for r in conn.execute('''SELECT s.id,s.revision,s.day,s.kind AS role,s.title,r.coverage,x.quote
            FROM knowledge_card_contexts x JOIN knowledge_sources s ON s.id=x.source_id AND s.revision=x.revision
            JOIN knowledge_revisions r ON r.source_id=s.id AND r.revision=s.revision
            WHERE x.card_id=? AND s.scope=?''', (card_id, scope))]

    def save_cover(self, scope, entity_id, cover, revision):
        """An editorial cover is not a new assertion or a lock on the factual body."""
        self.sync(scope)
        with self.store.transaction() as conn:
            row = self.resolve(conn, scope, entity_id, revision)
            if cover is None:
                conn.execute('DELETE FROM knowledge_entity_covers WHERE entity_id=?', (row['id'],))
            else:
                if not isinstance(cover, dict):
                    raise ValueError('封面必须为结构化内容')
                value = cover_for(json.loads(row['data']) | {'cover': cover}, locked=True)
                conn.execute('INSERT OR REPLACE INTO knowledge_entity_covers VALUES(?,?)', (row['id'], dump(value)))
            self.rebuild(conn, scope, row['id'], 'cover_edit', force=True)
            current = conn.execute('SELECT revision FROM knowledge_entities WHERE id=?', (row['id'],)).fetchone()[0]
            return {'id': row['id'], 'edit_revision': current,
                    'card': self.card(conn, self.resolve(conn, scope, row['id']))}

    def overview(self, scope, *, day='', domain='', topic='', query='', offset=0, kind='', sort='recent', limit=40):
        from .digest import DOMAINS, KINDS
        from .catalog import KnowledgeCatalog
        catalog = KnowledgeCatalog(self.store)
        if not isinstance(topic, str) or len(topic) > 60 or domain and domain not in {d['id'] for d in catalog.overview(scope)['domains']} or kind and kind not in KINDS:
            raise ValueError('知识库筛选无效')
        if sort not in {'recent', 'oldest', 'title', 'manual'} or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('知识库排序或分页无效')
        if day:
            day = self.store.validate_day(day)
        self.sync(scope)
        with closing(self.store._connect()) as conn:
            conn.execute('BEGIN')
            # SQL paging first, bounded source/detail payload only for selected entities.
            base = """ FROM knowledge_entities e WHERE e.scope=? AND e.redirect='' AND e.hidden=0
                AND e.data<>'{}' AND EXISTS(SELECT 1 FROM knowledge_entity_members m JOIN knowledge_sources s
                    ON s.id=m.source_id AND s.revision=m.source_revision
                    WHERE m.entity_id=e.id AND s.scope=e.scope)"""
            counts = dict(conn.execute("SELECT json_extract(e.data,'$.domain'),COUNT(*)" + base + " GROUP BY 1", (scope,)))
            filtered, args = base, [scope]
            for name, value in [('domain', domain), ('topic', topic), ('kind', kind)]:
                if value:
                    filtered += f" AND json_extract(e.data,'$.{name}')=?"
                    args.append(value)
            if day:
                # Date filtering and search both use that day's actual fragments.
                filtered += """ AND EXISTS(SELECT 1 FROM knowledge_entity_members m JOIN knowledge_sources s
                    ON s.id=m.source_id AND s.revision=m.source_revision WHERE m.entity_id=e.id AND s.day=?
                    AND (?='' OR instr(lower(m.data),?)>0))"""
                args.extend([day, query, query.lower()])
            elif query:
                filtered += ' AND instr(lower(e.data),?)>0'
                args.append(query.lower())
            total = conn.execute('SELECT COUNT(*)' + filtered, args).fetchone()[0]
            stamp = "(SELECT MAX(s.occurred_at) FROM knowledge_entity_members m JOIN knowledge_sources s ON s.id=m.source_id AND s.revision=m.source_revision WHERE m.entity_id=e.id)"
            order = {'recent': stamp + ' DESC', 'oldest': stamp, 'title': "json_extract(e.data,'$.title') COLLATE NOCASE",
                     'manual': 'e.position,' + stamp + ' DESC'}[sort]
            if domain and sort == 'recent':
                order = "json_extract(e.data,'$.topic')," + order
            rows = conn.execute('SELECT e.*' + filtered + ' ORDER BY ' + order + ',e.id LIMIT ? OFFSET ?', (*args, limit, offset)).fetchall()
            cards = [self.card(conn, row, day) for row in rows]
            states = dict(conn.execute('''SELECT j.status,COUNT(*) FROM knowledge_digest_jobs j JOIN knowledge_sources s
                ON s.id=j.source_id AND s.revision=j.revision WHERE s.scope=? GROUP BY j.status''', (scope,)))
            failed = conn.execute('''SELECT j.error FROM knowledge_digest_jobs j JOIN knowledge_sources s
                ON s.id=j.source_id AND s.revision=j.revision WHERE s.scope=? AND j.status='failed' LIMIT 1''', (scope,)).fetchone()
            parsing = dict(conn.execute('''SELECT j.status,COUNT(*) FROM knowledge_jobs j JOIN knowledge_sources s
                ON s.id=j.source_id WHERE s.scope=? GROUP BY j.status''', (scope,)))
            raw_count = conn.execute('SELECT COUNT(*) FROM knowledge_sources WHERE scope=?', (scope,)).fetchone()[0]
            progress = self.progress(conn, scope)
            directory = catalog.read(conn, scope)
            domains = [d | {'count': counts.get(d['id'], 0)} for d in directory['domains']]
        return {'domains': domains, 'catalog_revision': directory['revision'],
                'cards': [c for c in cards if c], 'total': total, 'has_more': total > offset + limit,
                'next_offset': offset + len(cards), 'states': states, 'error': failed[0] if failed else '',
                'raw_count': raw_count, 'total_cards': sum(counts.values()), 'types': KINDS, 'parsing': parsing,
                'consolidation': progress}

    @staticmethod
    def progress(conn, scope):
        states = dict(conn.execute('''SELECT j.status,COUNT(*) FROM knowledge_consolidation_jobs j JOIN knowledge_entities e
            ON e.id=j.entity_id AND e.revision=j.revision WHERE e.scope=? AND e.redirect='' AND e.hidden=0 GROUP BY j.status''', (scope,)))
        timing = conn.execute('''SELECT MIN(NULLIF(j.started,0)),MAX(j.finished) FROM knowledge_consolidation_jobs j
            JOIN knowledge_entities e ON e.id=j.entity_id WHERE e.scope=?''', (scope,)).fetchone()
        pending = conn.execute("SELECT COUNT(*) FROM knowledge_relations r JOIN knowledge_entities a ON a.id=r.a JOIN knowledge_entities b ON b.id=r.b WHERE r.scope=? AND r.status='pending' AND a.revision=r.a_revision AND b.revision=r.b_revision AND a.redirect='' AND b.redirect='' AND a.hidden=0 AND b.hidden=0", (scope,)).fetchone()[0]
        merges = conn.execute('SELECT COUNT(*) FROM knowledge_merge_history WHERE scope=? AND undone=0', (scope,)).fetchone()[0]
        return states | {'suggestions': pending, 'merges': merges,
                         'elapsed_seconds': max(0, int((time.time() if states.get('running') else timing[1] or time.time()) - timing[0])) if timing[0] else 0}

    def candidates(self, conn, scope, row):
        data = json.loads(row['data'])
        words = search_tokens(' '.join([data['title'], data['topic'], data['summary']]))[:64]
        if not words:
            return []
        expression = ' OR '.join('"' + word.replace('"', '""') + '"' for word in words)
        rows = conn.execute('''SELECT e.* FROM knowledge_entity_fts f JOIN knowledge_entities e ON e.id=f.entity_id
            WHERE knowledge_entity_fts MATCH ? AND f.scope=? AND e.scope=? AND e.id<>? AND e.redirect=''
            AND e.hidden=0 AND json_extract(e.data,'$.domain')=? AND json_extract(e.data,'$.kind')='knowledge'
            ORDER BY rank LIMIT 10''', (expression, scope, scope, row['id'], data['domain'])).fetchall()
        return [r for r in rows if not self.separated(conn, scope, row['id'], r['id'])]

    @staticmethod
    def separated(conn, scope, a, b):
        return conn.execute('SELECT 1 FROM knowledge_separations WHERE scope=? AND a=? AND b=?', (scope, *sorted([a, b]))).fetchone() is not None

    @staticmethod
    def separate(conn, scope, a, b):
        conn.execute('INSERT OR IGNORE INTO knowledge_separations VALUES(?,?,?)', (scope, *sorted([a, b])))

    @staticmethod
    def automatic_safe(a, b):
        if a.get('kind') != 'knowledge' or b.get('kind') != 'knowledge' or a['domain'] != b['domain']:
            return False
        if a.get('format') == 'problem' or b.get('format') == 'problem':
            if (a.get('question'), a.get('answer')) != (b.get('question'), b.get('answer')):
                return False
        def factual_text(data):
            return '\n'.join([*(str(data.get(k, '')) for k in ('summary', 'question', 'answer', 'details')), *data.get('points', [])])
        text_a, text_b = factual_text(a), factual_text(b)
        # Numeric/code/version changes need explicit review, irrespective of model confidence.
        # The same numbers assigned to different objects/conditions are not identical evidence.
        numbers = lambda t: {re.sub(r'\s+', '', s) for s in re.split(r'[\n。；;]', t) if re.search(r'\d', s)}
        code = lambda t: re.findall(r'```[\s\S]*?```|`[^`]+`', t)
        formula = lambda t: re.findall(r'\$\$[\s\S]*?\$\$|\$[^\n$]+\$|\\\[[\s\S]*?\\\]|\\\([^\n]*?\\\)', t)
        return numbers(text_a) == numbers(text_b) and code(text_a) == code(text_b) and formula(text_a) == formula(text_b)

    def merge(self, scope, target, incoming, *, target_revision, incoming_revision,
              relation='complement', reason='用户整合', automatic=False, job=None):
        if relation not in {'equivalent', 'complement', 'exact'} or not isinstance(reason, str) or len(reason) > 1000:
            raise ValueError('整合关系无效')
        self.sync(scope)
        with self.store.transaction() as conn:
            if job is not None and not self.owns_job(conn, job):
                raise RevisionConflict('后台审核租约已失效，将由当前任务重新审核')
            a = self.resolve(conn, scope, target, target_revision)
            b = self.resolve(conn, scope, incoming, incoming_revision)
            if a['id'] == b['id']:
                raise ValueError('这两张卡已经属于同一知识')
            if automatic and (a['locked'] or b['locked'] or self.separated(conn, scope, a['id'], b['id'])
                              or not self.automatic_safe(json.loads(a['data']), json.loads(b['data']))):
                raise RevisionConflict('需要保留独立或人工确认的知识')
            before = []
            for row in (a, b):
                before.append({'entity': dict(row), 'members': [m[0] for m in conn.execute(
                    'SELECT card_id FROM knowledge_entity_members WHERE entity_id=?', (row['id'],))],
                    'cover': next((c[0] for c in conn.execute('SELECT data FROM knowledge_entity_covers WHERE entity_id=?', (row['id'],))), None),
                    'relations': {m['card_id']: m['relation'] for m in self.members(conn, scope, row['id'])}})
            if before[0]['cover'] is None and before[1]['cover'] is not None:
                conn.execute('INSERT OR REPLACE INTO knowledge_entity_covers VALUES(?,?)', (a['id'], before[1]['cover']))
            if a['locked']:
                for m in self.members(conn, scope, a['id']):
                    if json.loads(m['metadata']).get('manual_card'):
                        conn.execute("INSERT OR REPLACE INTO knowledge_member_relations VALUES(?,'authoritative')", (m['card_id'],))
                for member_id in before[1]['members']:
                    conn.execute("UPDATE knowledge_member_relations SET relation='complement' WHERE card_id=? AND relation='authoritative'", (member_id,))
            conn.execute('UPDATE knowledge_entity_members SET entity_id=? WHERE entity_id=? AND scope=?', (a['id'], b['id'], scope))
            if relation == 'equivalent':
                for member_id in before[1]['members']:
                    conn.execute("INSERT OR REPLACE INTO knowledge_member_relations VALUES(?,'equivalent')", (member_id,))
            conn.execute('UPDATE knowledge_entities SET redirect=?,revision=revision+1 WHERE id=?', (a['id'], b['id']))
            conn.execute('UPDATE knowledge_entities SET locked=? WHERE id=?', (max(a['locked'], b['locked']), a['id']))
            conn.execute('DELETE FROM knowledge_entity_fts WHERE entity_id=?', (b['id'],))
            self.rebuild(conn, scope, a['id'], 'merge', force=True)
            after = {r['id']: conn.execute('SELECT revision FROM knowledge_entities WHERE id=?', (r['id'],)).fetchone()[0] for r in (a, b)}
            history_id = uuid.uuid4().hex
            conn.execute('INSERT INTO knowledge_merge_history VALUES(?,?,?,?,?,?,?,?,?,0)',
                         (history_id, scope, a['id'], b['id'], relation, reason, dump(before), dump(after), time.time()))
            return {'id': a['id'], 'history_id': history_id, 'edit_revision': after[a['id']]}

    @staticmethod
    def owns_job(conn, job):
        return conn.execute("""SELECT 1 FROM knowledge_consolidation_jobs
            WHERE entity_id=? AND revision=? AND token=? AND status='running' AND lease>?""",
            (*job, time.time())).fetchone() is not None

    def undo(self, scope, history_id):
        self.sync(scope)
        with self.store.transaction() as conn:
            h = conn.execute('SELECT * FROM knowledge_merge_history WHERE scope=? AND id=? AND undone=0', (scope, history_id)).fetchone()
            if not h:
                raise ValueError('整合记录不存在或已经撤销')
            after, before = json.loads(h['after_state']), json.loads(h['before_state'])
            for entity_id, revision in after.items():
                row = conn.execute('SELECT revision FROM knowledge_entities WHERE scope=? AND id=?', (scope, entity_id)).fetchone()
                if not row or row[0] != revision:
                    raise RevisionConflict('整合后内容已有变化，请使用拆分，避免覆盖新内容')
            for snapshot in before:
                old = snapshot['entity']
                conn.execute('DELETE FROM knowledge_entity_covers WHERE entity_id=?', (old['id'],))
                if snapshot.get('cover') is not None:
                    conn.execute('INSERT INTO knowledge_entity_covers VALUES(?,?)', (old['id'], snapshot['cover']))
                for card_id in snapshot['members']:
                    conn.execute('UPDATE knowledge_entity_members SET entity_id=? WHERE scope=? AND card_id=?', (old['id'], scope, card_id))
                    conn.execute('INSERT OR REPLACE INTO knowledge_member_relations VALUES(?,?)', (card_id, snapshot.get('relations', {}).get(card_id, 'complement')))
                conn.execute('UPDATE knowledge_entities SET redirect=?,hidden=?,position=?,locked=? WHERE id=?',
                             (old['redirect'], old['hidden'], old['position'], old['locked'], old['id']))
                self.rebuild(conn, scope, old['id'], 'undo', force=True)
            self.separate(conn, scope, h['target'], h['incoming'])
            conn.execute('UPDATE knowledge_merge_history SET undone=1 WHERE id=?', (history_id,))

    def split(self, scope, entity_id, member_id, revision):
        self.sync(scope)
        with self.store.transaction() as conn:
            row = self.resolve(conn, scope, entity_id, revision)
            members = self.members(conn, scope, row['id'])
            if len(members) < 2 or member_id not in {m['card_id'] for m in members}:
                raise ValueError('请选择主卡中有效的独立来源知识')
            new_id = uuid.uuid4().hex
            member = next(m for m in members if m['card_id'] == member_id)
            manual = bool(json.loads(member['metadata']).get('manual_card'))
            conn.execute('INSERT INTO knowledge_entities(id,scope,locked,created,updated) VALUES(?,?,?,?,?)', (new_id, scope, int(manual), time.time(), time.time()))
            conn.execute('UPDATE knowledge_entity_members SET entity_id=? WHERE card_id=? AND scope=?', (new_id, member_id, scope))
            self.separate(conn, scope, row['id'], new_id)
            self.rebuild(conn, scope, row['id'], 'split', force=True)
            self.rebuild(conn, scope, new_id, 'split', force=True)
            return {'id': new_id}

    def history(self, scope, entity_id):
        self.sync(scope)
        with closing(self.store._connect()) as conn:
            row = self.resolve(conn, scope, entity_id)
            events = conn.execute('''SELECT id,target,incoming,relation,reason,created,undone,before_state,after_state
                FROM knowledge_merge_history WHERE scope=? AND (target=? OR incoming=?) ORDER BY created DESC LIMIT 30''', (scope, row['id'], row['id'])).fetchall()
            history = []
            for event in events:
                item = dict(event)
                before = json.loads(item.pop('before_state'))
                item['before'] = [{'id': s['entity']['id'], 'data': json.loads(s['entity']['data'])} for s in before]
                item['after'] = json.loads(item.pop('after_state'))
                history.append(item)
            return {'events': history, 'members': [{'id': m['card_id'], 'source_id': m['source_id'], 'revision': m['source_revision'],
                        'data': json.loads(m['data'])} for m in self.members(conn, scope, row['id'])], 'revision': row['revision']}

    def suggestions(self, scope):
        self.sync(scope)
        with closing(self.store._connect()) as conn:
            rows = conn.execute('''SELECT r.*,a.data AS a_data,b.data AS b_data FROM knowledge_relations r
                JOIN knowledge_entities a ON a.id=r.a AND a.revision=r.a_revision AND a.redirect='' AND a.hidden=0
                JOIN knowledge_entities b ON b.id=r.b AND b.revision=r.b_revision AND b.redirect='' AND b.hidden=0
                WHERE r.scope=? AND r.status='pending' ORDER BY r.created DESC LIMIT 40''', (scope,)).fetchall()
            return [dict(r) | {'a_data': json.loads(r['a_data']), 'b_data': json.loads(r['b_data'])} for r in rows]

    def decide(self, scope, relation_id, accept):
        if type(accept) is not bool:
            raise ValueError('请选择整合或保持独立')
        with closing(self.store._connect()) as conn:
            row = conn.execute("SELECT * FROM knowledge_relations WHERE scope=? AND id=? AND status='pending'", (scope, relation_id)).fetchone()
        if not row:
            raise ValueError('建议已处理，请刷新')
        if accept:
            if row['relation'] not in {'equivalent', 'complement'}:
                raise ValueError('冲突或相关知识应保留独立；可在详情中对照')
            result = self.merge(scope, row['a'], row['b'], target_revision=row['a_revision'], incoming_revision=row['b_revision'], relation=row['relation'], reason=row['reason'])
        else:
            result = {}
        with self.store.transaction() as conn:
            if not accept:
                self.resolve(conn, scope, row['a'], row['a_revision'])
                self.resolve(conn, scope, row['b'], row['b_revision'])
                self.separate(conn, scope, row['a'], row['b'])
            conn.execute('UPDATE knowledge_relations SET status=? WHERE id=?', ('accepted' if accept else 'separate', relation_id))
        return result
