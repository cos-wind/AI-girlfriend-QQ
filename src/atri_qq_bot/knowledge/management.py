"""User-owned cards and scoped, evidence-backed graph data."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from .digest import DOMAINS, KINDS, KnowledgeDigest, card_content
from .store import LOCAL_TIME, KnowledgeStore, RevisionConflict


class KnowledgeLibrary:
    def __init__(self, store: KnowledgeStore):
        self.store = store
        self.editor = KnowledgeDigest(store)

    @staticmethod
    def _validate(value):
        if not isinstance(value, dict) or value.get('domain') not in DOMAINS or value.get('kind') not in KINDS:
            raise ValueError('请选择有效的领域与类型')
        data = {}
        for name, limit in [('title', 100), ('topic', 60), ('summary', 20000)]:
            text = value.get(name)
            if not isinstance(text, str) or not text.strip() or len(text) > limit:
                raise ValueError(f'{name} 不能为空且最多 {limit} 字')
            data[name] = text.strip()
        points = value.get('points', [])
        if not isinstance(points, list) or len(points) > 30 or any(not isinstance(p, str) or len(p) > 2000 for p in points):
            raise ValueError('最多30条要点，每条最多2000字')
        return data | {'domain': value['domain'], 'kind': value['kind'], 'points': [p for p in points if p.strip()]} | card_content(value)

    @staticmethod
    def _card(conn, scope, card_id, revision=None):
        row = conn.execute('''SELECT c.*,s.metadata,COALESCE(m.revision,0) AS edit_revision
            FROM knowledge_cards c JOIN knowledge_sources s ON s.id=c.source_id AND s.revision=c.revision
            LEFT JOIN knowledge_card_preferences m ON m.scope=s.scope AND m.signature=c.signature
            WHERE s.scope=? AND c.id=? AND COALESCE(m.hidden,0)=0''', (scope, card_id)).fetchone()
        if not row:
            raise ValueError('卡片已删除或不属于当前知识库，请刷新')
        if revision is not None and (type(revision) is not int or revision != row['edit_revision']):
            raise RevisionConflict('卡片已被修改，请刷新后再编辑')
        return row

    def save(self, scope, value, *, card_id='', revision=0):
        data = self._validate(value)
        text = '\n\n'.join(filter(None, [data['title'], data['summary'], data['question'], data['answer'], data['details'], '\n'.join(data['points']), '、'.join(data['terms'])]))
        if data['charts']:
            text += '\n\n图表数据与来源：\n' + json.dumps(data['charts'], ensure_ascii=False)
        with self.store.transaction() as conn:
            row = self._card(conn, scope, card_id, revision) if card_id else None
            metadata = json.loads(row['metadata']) if row else {}
            manual = bool(metadata.get('manual_card'))
            stamp = time.time()
            source_id = row['source_id'] if manual else uuid.uuid4().hex
            new_revision = row['revision'] + 1 if manual else 1
            new_id = row['id'] if manual else uuid.uuid4().hex
            signature = row['signature'] if manual else 'manual:' + new_id
            if manual:
                conn.execute('UPDATE knowledge_sources SET revision=?,title=? WHERE id=?', (new_revision, data['title'], source_id))
            else:
                metadata = {'manual_card': True}
                if row:
                    # Preserve provenance separately from the user's revised assertion.
                    metadata['edited_from'] = {'source_id': row['source_id'], 'revision': row['revision'],
                                               'quote': json.loads(row['data']).get('quote', '')}
                    conn.execute('''INSERT INTO knowledge_card_preferences(scope,signature,hidden,revision) VALUES(?,?,1,1)
                        ON CONFLICT(scope,signature) DO UPDATE SET hidden=1,revision=revision+1''', (scope, row['signature']))
                conn.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (source_id, scope, 'note', data['title'], stamp, datetime.fromtimestamp(stamp, LOCAL_TIME).date().isoformat(),
                     stamp, 1, None, '', '', None, json.dumps(metadata, ensure_ascii=False)))
            self.store._write_revision(conn, scope, source_id, new_revision, text, None, 'user_authored_card')
            card_data = data | {'quote': text[:600]}
            conn.execute('''INSERT OR REPLACE INTO knowledge_cards VALUES(?,?,?,?,?,?,?,?,?)''',
                (new_id, source_id, new_revision, -1, data['domain'], data['topic'], data['kind'], signature,
                 json.dumps(card_data, ensure_ascii=False)))
            version = row['edit_revision'] + 1 if manual else 1
            conn.execute('''INSERT INTO knowledge_card_preferences(scope,signature,revision) VALUES(?,?,?)
                ON CONFLICT(scope,signature) DO UPDATE SET revision=excluded.revision''', (scope, signature, version))
        return {'id': new_id, 'edit_revision': version}

    def delete(self, scope, card_id, revision):
        with self.store.transaction() as conn:
            row = self._card(conn, scope, card_id, revision)
            conn.execute('''INSERT INTO knowledge_card_preferences(scope,signature,hidden,revision) VALUES(?,?,1,1)
                ON CONFLICT(scope,signature) DO UPDATE SET hidden=1,revision=revision+1''', (scope, row['signature']))

    def reorder(self, scope, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('排序列表无效')
        with self.store.transaction() as conn:
            rows = [self._card(conn, scope, i) for i in ids]
            for position, row in enumerate(rows):
                conn.execute('''INSERT INTO knowledge_card_preferences(scope,signature,position) VALUES(?,?,?)
                    ON CONFLICT(scope,signature) DO UPDATE SET position=excluded.position''', (scope, row['signature'], position))

    def graph(self, scope, **filters):
        cards, offset = [], 0
        while len(cards) < 500:
            page = self.editor.overview(scope, offset=offset, **filters)
            cards.extend(page['cards'][:500-len(cards)])
            if not page['has_more']:
                break
            offset = page['next_offset']
        nodes, edges, topics, domains, sources = [], [], set(), set(), {}
        for card in cards:
            domain = 'domain:' + card['domain']
            topic = domain + ':topic:' + card['topic']
            if domain not in domains:
                nodes.append({'id': domain, 'label': DOMAINS[card['domain']][0], 'type': 'domain', 'domain': card['domain']})
                domains.add(domain)
            if topic not in topics:
                nodes.append({'id': topic, 'label': card['topic'], 'type': 'topic', 'domain': card['domain']})
                edges.append({'source': domain, 'target': topic, 'kind': 'contains'})
                topics.add(topic)
            nodes.append({'id': card['id'], 'label': card['title'], 'type': 'card', 'domain': card['domain'], 'card': card})
            edges.append({'source': topic, 'target': card['id'], 'kind': 'contains'})
            for evidence in card['evidence']:
                key = (evidence['id'], evidence['revision'])
                if key in sources:
                    edges.append({'source': sources[key], 'target': card['id'], 'kind': 'shared_source'})
                else:
                    sources[key] = card['id']
        return {'nodes': nodes, 'edges': edges, 'total': page['total'], 'shown': len(cards),
                'truncated': page['total'] > len(cards)}
