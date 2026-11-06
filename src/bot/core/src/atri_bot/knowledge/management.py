"""User-owned cards and scoped, evidence-backed graph data."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from atri_bot.knowledge.digest import DOMAINS, KINDS, KnowledgeDigest, card_content
from atri_bot.knowledge.store import LOCAL_TIME, KnowledgeStore, RevisionConflict


class KnowledgeLibrary:
    def __init__(self, store: KnowledgeStore):
        self.store = store
        self.editor = KnowledgeDigest(store)

    @staticmethod
    def _validate(value, domains=DOMAINS):
        if not isinstance(value, dict) or value.get('domain') not in domains or value.get('kind') not in KINDS:
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

    def save(self, scope, value, *, card_id='', revision=0):
        from .entities import KnowledgeEntities, dump, fingerprint
        from .covers import cover_for
        from .catalog import KnowledgeCatalog
        catalog = KnowledgeCatalog(self.store)
        entities = KnowledgeEntities(self.store)
        entities.sync(scope)
        data = self._validate(value, {d['id'] for d in catalog.overview(scope)['domains']})
        if 'cover' in value:
            data['cover'] = cover_for(data | {'cover': value['cover']}, locked=True)
        text = '\n\n'.join(filter(None, [data['title'], data['summary'], data['question'], data['answer'], data['details'], '\n'.join(data['points']), '、'.join(data['terms'])]))
        if data.get('cover'):
            text += '\n\n封面：' + dump(data['cover'])
        if data['charts']:
            text += '\n\n图表数据与来源：\n' + dump(data['charts'])
        with self.store.transaction() as conn:
            if data['domain'] not in {d['id'] for d in catalog.read(conn, scope)['domains']}:
                raise RevisionConflict('目标知识库已删除，请重新选择')
            row = entities.resolve(conn, scope, card_id, revision) if card_id else None
            stamp = time.time()
            entity_id = row['id'] if row else uuid.uuid4().hex
            members = entities.members(conn, scope, entity_id) if row else []
            manuals = [m for m in members if json.loads(m['metadata']).get('manual_card')]
            manual = manuals[-1] if manuals else None
            source_id = manual['source_id'] if manual else uuid.uuid4().hex
            new_revision = manual['source_revision'] + 1 if manual else 1
            member_id = manual['card_id'] if manual else uuid.uuid4().hex
            if manual:
                conn.execute('UPDATE knowledge_sources SET revision=?,title=? WHERE id=?', (new_revision, data['title'], source_id))
            else:
                metadata = {'manual_card': True, 'entity_id': entity_id}
                if row:
                    metadata['edited_from'] = [{'source_id': m['source_id'], 'revision': m['source_revision']} for m in members]
                conn.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (source_id, scope, 'note', data['title'], stamp, datetime.fromtimestamp(stamp, LOCAL_TIME).date().isoformat(),
                     stamp, 1, None, '', '', None, dump(metadata)))
            self.store._write_revision(conn, scope, source_id, new_revision, text, None, 'user_authored_card')
            card_data = data | {'quote': text[:600]}
            signature = 'manual:' + member_id
            conn.execute('INSERT OR REPLACE INTO knowledge_cards VALUES(?,?,?,?,?,?,?,?,?)',
                (member_id, source_id, new_revision, -1, data['domain'], data['topic'], data['kind'], signature, dump(card_data)))
            if not row:
                conn.execute('INSERT INTO knowledge_entities(id,scope,locked,created,updated) VALUES(?,?,1,?,?)', (entity_id, scope, stamp, stamp))
            else:
                conn.execute('UPDATE knowledge_entities SET locked=1 WHERE id=?', (entity_id,))
            conn.execute('INSERT OR REPLACE INTO knowledge_entity_members VALUES(?,?,?,?,?,?,?)',
                (member_id, entity_id, scope, source_id, new_revision, 'manual:' + source_id, dump(card_data)))
            conn.execute("UPDATE knowledge_member_relations SET relation='complement' WHERE relation='authoritative' AND card_id IN (SELECT card_id FROM knowledge_entity_members WHERE entity_id=?)", (entity_id,))
            conn.execute("INSERT OR REPLACE INTO knowledge_member_relations VALUES(?,'authoritative')", (member_id,))
            conn.execute('DELETE FROM knowledge_entity_locations WHERE entity_id=?', (entity_id,))
            entities.rebuild(conn, scope, entity_id, 'user_edit', force=True)
            version = conn.execute('SELECT revision FROM knowledge_entities WHERE id=?', (entity_id,)).fetchone()[0]
            current = entities.card(conn, entities.resolve(conn, scope, entity_id))
        return {'id': entity_id, 'edit_revision': version, 'card': current}

    def move(self, scope, cards, domain, topic):
        """Atomic placement override; moving never authors evidence or locks the body."""
        from .catalog import KnowledgeCatalog
        from .entities import KnowledgeEntities
        if not isinstance(cards, list) or not 1 <= len(cards) <= 500 or any(not isinstance(c, dict) for c in cards):
            raise ValueError('每次请选择1至500张卡片')
        if not isinstance(topic, str) or not topic.strip() or len(topic) > 60:
            raise ValueError('主题目录为1至60字')
        catalog = KnowledgeCatalog(self.store)
        entities = KnowledgeEntities(self.store)
        entities.sync(scope)
        with self.store.transaction() as conn:
            if domain not in {d['id'] for d in catalog.read(conn, scope)['domains']}:
                raise ValueError('目标知识库不存在')
            rows = []
            for card in cards:
                if type(card.get('revision')) is not int:
                    raise ValueError('卡片版本无效，请刷新后重试')
                rows.append(entities.resolve(conn, scope, card.get('id'), card['revision']))
            if len({r['id'] for r in rows}) != len(rows):
                raise ValueError('选择包含重复或已合并的卡片')
            for row in rows:
                conn.execute('INSERT OR REPLACE INTO knowledge_entity_locations VALUES(?,?,?)', (row['id'], domain, topic.strip()))
                entities.rebuild(conn, scope, row['id'], 'user_move', force=True)
            current = [entities.card(conn, entities.resolve(conn, scope, row['id'])) for row in rows]
        return {'moved': len(rows), 'cards': current}

    def delete(self, scope, card_id, revision):
        from .entities import KnowledgeEntities
        entities = KnowledgeEntities(self.store)
        entities.sync(scope)
        with self.store.transaction() as conn:
            row = entities.resolve(conn, scope, card_id, revision)
            conn.execute('UPDATE knowledge_entities SET hidden=1,revision=revision+1 WHERE id=?', (row['id'],))
            conn.execute('DELETE FROM knowledge_entity_fts WHERE entity_id=?', (row['id'],))

    def reorder(self, scope, ids):
        from .entities import KnowledgeEntities
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('排序列表无效')
        entities = KnowledgeEntities(self.store)
        entities.sync(scope)
        with self.store.transaction() as conn:
            rows = [entities.resolve(conn, scope, i) for i in ids]
            if len({r['id'] for r in rows}) != len(rows):
                raise ValueError('排序包含已整合的重复知识')
            for position, row in enumerate(rows):
                conn.execute('UPDATE knowledge_entities SET position=? WHERE id=?', (position, row['id']))

    def graph(self, scope, **filters):
        from .catalog import KnowledgeCatalog
        names = {d['id']: d['name'] for d in KnowledgeCatalog(self.store).overview(scope)['domains']}
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
                nodes.append({'id': domain, 'label': names.get(card['domain'], card['domain']), 'type': 'domain', 'domain': card['domain']})
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
