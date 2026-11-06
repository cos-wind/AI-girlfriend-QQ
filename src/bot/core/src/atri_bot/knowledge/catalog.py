"""Scoped library names and order, independent of extraction and evidence."""
from __future__ import annotations

from contextlib import closing
import uuid

from .digest import DOMAINS
from .store import RevisionConflict


class KnowledgeCatalog:
    def __init__(self, store):
        self.store = store
        with store.transaction() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS knowledge_libraries (
                    scope TEXT NOT NULL,id TEXT NOT NULL,name TEXT NOT NULL,description TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 2147483647,PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS knowledge_catalog_state (
                    scope TEXT PRIMARY KEY,revision INTEGER NOT NULL);
            ''')

    @staticmethod
    def read(conn, scope):
        domains = {key: {'id': key, 'name': value[0], 'description': value[1], 'builtin': True,
                         'position': index} for index, (key, value) in enumerate(DOMAINS.items())}
        for row in conn.execute('SELECT * FROM knowledge_libraries WHERE scope=?', (scope,)):
            domains[row['id']] = dict(row) | {'builtin': row['id'] in DOMAINS}
            domains[row['id']].pop('scope', None)
        revision = conn.execute('SELECT revision FROM knowledge_catalog_state WHERE scope=?', (scope,)).fetchone()
        return {'domains': sorted(domains.values(), key=lambda d: (d['position'], d['id'])),
                'revision': revision[0] if revision else 0}

    def overview(self, scope):
        with closing(self.store._connect()) as conn:
            conn.execute('BEGIN')
            return self.read(conn, scope)

    @staticmethod
    def check(conn, scope, revision):
        data = KnowledgeCatalog.read(conn, scope)
        if type(revision) is not int or revision != data['revision']:
            raise RevisionConflict('知识库目录已更新，请重新打开管理窗口')
        return data

    @staticmethod
    def bump(conn, scope):
        conn.execute('INSERT INTO knowledge_catalog_state VALUES(?,1) ON CONFLICT(scope) DO UPDATE SET revision=revision+1', (scope,))

    def save(self, scope, *, name, description='', id='', revision):
        if not isinstance(name, str) or not name.strip() or len(name) > 40:
            raise ValueError('知识库名称为1至40字')
        if not isinstance(description, str) or len(description) > 200:
            raise ValueError('知识库说明最多200字')
        with self.store.transaction() as conn:
            data = self.check(conn, scope, revision)
            existing = next((d for d in data['domains'] if d['id'] == id), None)
            if id and existing is None:
                raise ValueError('知识库不存在或不属于当前范围')
            if any(d['id'] != id and d['name'].casefold() == name.strip().casefold() for d in data['domains']):
                raise ValueError('已有同名知识库')
            id = id or 'custom:' + uuid.uuid4().hex
            position = existing['position'] if existing else max(d['position'] for d in data['domains']) + 1
            conn.execute('INSERT OR REPLACE INTO knowledge_libraries VALUES(?,?,?,?,?)', (scope, id, name.strip(), description.strip(), position))
            self.bump(conn, scope)
            return self.read(conn, scope) | {'id': id}

    def reorder(self, scope, ids, revision):
        with self.store.transaction() as conn:
            data = self.check(conn, scope, revision)
            if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)) or set(ids) != {d['id'] for d in data['domains']}:
                raise ValueError('请提交完整且不重复的知识库排序')
            for domain in data['domains']:
                conn.execute('INSERT OR REPLACE INTO knowledge_libraries VALUES(?,?,?,?,?)', (scope, domain['id'], domain['name'], domain['description'], ids.index(domain['id'])))
            self.bump(conn, scope)
            return self.read(conn, scope)

    def delete(self, scope, id, revision):
        from .entities import KnowledgeEntities
        KnowledgeEntities(self.store).sync(scope)
        with self.store.transaction() as conn:
            data = self.check(conn, scope, revision)
            if id in DOMAINS:
                raise ValueError('基础领域可改名和排序；自建知识库支持删除')
            if not any(d['id'] == id for d in data['domains']):
                raise ValueError('知识库不存在')
            if conn.execute("SELECT 1 FROM knowledge_entities WHERE scope=? AND redirect='' AND hidden=0 AND json_extract(data,'$.domain')=? LIMIT 1", (scope, id)).fetchone():
                raise ValueError('请先移动该知识库中的卡片，再删除空库')
            # Historical evidence can still name this library; deletion never removes it.
            conn.execute('DELETE FROM knowledge_libraries WHERE scope=? AND id=?', (scope, id))
            self.bump(conn, scope)
            return self.read(conn, scope)
