"""A video without public subtitles can still supply clearly labelled metadata."""
import json
from types import SimpleNamespace

from atri_qq_bot.knowledge import KnowledgeStore, ingestion
from atri_qq_bot.toolbox import ToolAnalyzer


def test_short_link_without_subtitles_archives_public_metadata(monkeypatch, tmp_path):
    bvid = 'BV1abcabcabc'

    async def fetch(self, url):
        if 'x/web-interface/view' in url:
            assert bvid in url
            data = {'code': 0, 'data': {'bvid': bvid, 'title': 'PCL2 至暗时刻',
                    'desc': '作者对账号事件的说明', 'owner': {'name': 'UP主'}, 'pages': [{'cid': 123}]}}
        elif 'x/player/v2' in url:
            data = {'code': 0, 'data': {'subtitle': {'subtitles': []}}}
        else:
            # Short-link redirect is the only place containing the BV number.
            return b'<html><body></body></html>', 'https://www.bilibili.com/video/' + bvid, 'text/html'
        return json.dumps(data, ensure_ascii=False).encode(), url, 'application/json'

    monkeypatch.setattr(ToolAnalyzer, '_fetch_url', fetch)
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3')
    source = store.create('desktop:owner', '', locator='https://b23.tv/Ms39EwZ', enqueue=True,
                          metadata={'import_url': True})
    ingestion.run_pending(store, SimpleNamespace(), max_jobs=1)
    saved = store.get('desktop:owner', source['id'])
    assert saved['job_status'] == 'done', saved['job_error']
    assert 'PCL2 至暗时刻' in saved['text'] and '作者对账号事件的说明' in saved['text']
    assert saved['coverage'] == 'bilibili_public_metadata_only'
    assert saved['metadata']['analysis']['read_level'] == 'partial_content'
    assert any('没有读到公开字幕' in s for s in saved['metadata']['analysis']['limitations'])


def test_rejected_bilibili_api_does_not_create_readable_material(monkeypatch, tmp_path):
    async def fetch(self, url):
        if 'api.bilibili.com' in url:
            return b'{"code":-412,"message":"request blocked"}', url, 'application/json'
        return b'<title>video</title>', 'https://www.bilibili.com/video/BV1abcabcabc', 'text/html'

    monkeypatch.setattr(ToolAnalyzer, '_fetch_url', fetch)
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3')
    source = store.create('desktop:owner', '', locator='https://www.bilibili.com/video/BV1abcabcabc',
                          enqueue=True, metadata={'import_url': True})
    ingestion.run_pending(store, SimpleNamespace(), max_jobs=1)
    saved = store.get('desktop:owner', source['id'])
    assert saved['job_status'] == 'failed'
    assert '-412' in saved['job_error'] and not saved['text']
