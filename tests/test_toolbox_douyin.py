import asyncio
import json
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from atri_qq_bot.toolbox import ToolAnalyzer
from atri_qq_bot.toolbox_parts.douyin import is_douyin_url, public_item
from atri_qq_bot.knowledge import KnowledgeStore, ingestion


SHORT = 'https://v.douyin.com/ydRFY-i7Q28/'
LANDING = 'https://www.douyin.com/note/7699095130908979967?previous_page=app_code_link'
ITEM_ID = '7699095130908979967'


def test_short_note_link_uses_public_share_caption(monkeypatch):
    analyzer = ToolAnalyzer(SimpleNamespace())
    calls = []
    item = {'aweme_id': ITEM_ID, 'desc': '学生认证代金券介绍', 'author': {'nickname': '发布者'}}

    async def fetch(url):
        calls.append(url)
        if url == SHORT:
            return b'<html><body></body><script>challenge()</script></html>', LANDING, 'text/html'
        assert url == f'https://www.iesdouyin.com/share/note/{ITEM_ID}/'
        payload = {'loaderData': {'note_(id)/page': {'videoInfoRes': {'item_list': [item]}}}}
        return ('<script>window._ROUTER_DATA = ' + json.dumps(payload) + ';</script>').encode(), url, 'text/html'

    monkeypatch.setattr(analyzer, '_fetch_url', fetch)
    result = asyncio.run(analyzer._analyze_url(SHORT))
    assert len(calls) == 2
    assert result.read_level == 'partial_content'
    assert '学生认证代金券介绍' in result.findings[0]
    assert result.knowledge_materials[0]['coverage'] == 'public_share_caption_only'
    assert '未读取图片' in result.limitations[0]


def test_empty_douyin_shell_fails_archive_with_specific_reason(monkeypatch, tmp_path):
    async def fetch(self, url):
        # An accessible HTML page is not proof of reading a work.
        return b'<title>Douyin</title><script>window._ROUTER_DATA={"loaderData":{}}</script>', LANDING, 'text/html'

    monkeypatch.setattr(ToolAnalyzer, '_fetch_url', fetch)
    async def unreadable(*args):
        return '网页读取失败：没有正文'
    monkeypatch.setattr('atri_qq_bot.llm_tools.web_page_tool.open_web_page', unreadable)
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3')
    source = store.create('desktop:owner', '', locator=SHORT, enqueue=True, metadata={'import_url': True})
    assert ingestion.run_pending(store, SimpleNamespace(), max_jobs=1) == 1
    saved = store.get('desktop:owner', source['id'])
    assert saved['job_status'] == 'failed'
    assert '图文作品 ' + ITEM_ID in saved['job_error']
    assert '未读到图片' in saved['job_error']
    assert not saved['text']


@pytest.mark.parametrize('format', ['router', 'render'])
def test_extract_requested_work_only(format):
    other = {'aweme_id': '123', 'desc': '推荐内容不能当作原作品'}
    expected = {'aweme_id': ITEM_ID, 'desc': '作品正文'}
    payload = json.dumps({'items': [other, expected]})
    page = ('<script>window._ROUTER_DATA = ' + payload + ';</script>' if format == 'router'
            else '<script id="RENDER_DATA" type="application/json">' + quote(payload) + '</script>')
    assert public_item(page, ITEM_ID) == expected
    assert public_item(page, 'missing') == {}


def test_douyin_domain_is_exact():
    assert is_douyin_url(SHORT)
    assert is_douyin_url('https://www.iesdouyin.com/share/note/123/')
    assert not is_douyin_url('https://douyin.com.example.org/note/123')
    assert not is_douyin_url('https://example.org/?url=https://douyin.com')
