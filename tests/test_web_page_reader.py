import asyncio
from types import SimpleNamespace

import httpx

from atri_qq_bot.llm_tools import web_page_tool as reader


def test_request_only_advertises_supported_decoders():
    advertised = {part.strip() for part in reader._request_headers()['Accept-Encoding'].split(',')}
    assert advertised <= set(httpx._decoders.SUPPORTED_DECODERS)


def test_empty_html_uses_same_reader_fallback(monkeypatch):
    async def public(url):
        pass

    calls = []

    async def fallback(url, max_chars, timeout):
        calls.append(url)
        return '已通过阅读代理读取网页：' + url + '\n实际正文'

    original = httpx.AsyncClient
    monkeypatch.setattr(reader, '_ensure_public_hostname', public)
    monkeypatch.setattr(reader, '_jina_reader_fallback', fallback)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(lambda req: httpx.Response(200,
            headers={'content-type': 'text/html'}, text='<html><body></body><script>challenge()</script></html>')), **kw))
    result = asyncio.run(reader.open_web_page({'url': 'https://example.org/item'}, SimpleNamespace()))
    assert calls == ['https://example.org/item']
    assert '实际正文' in result


def test_binary_garbage_is_not_readable_text():
    assert not reader.is_readable_page_text('\x01\ufffde\x00\ufffd\ufffd compressed data')
    assert not reader.is_readable_page_text('Warning: Target URL returned error 403: Forbidden')
    assert reader.is_readable_page_text('学生认证代金券介绍。\n可读的中文正文。')


def test_desktop_ingestion_and_qq_analyzer_share_reader_fallback(monkeypatch, tmp_path):
    from atri_qq_bot.toolbox import ToolAnalyzer
    from atri_qq_bot.knowledge import KnowledgeStore, ingestion
    url = 'https://v.douyin.com/ydRFY-i7Q28/'
    calls = []

    async def fetch(self, url):
        return b'<html><body></body></html>', 'https://www.douyin.com/note/7699095130908979967', 'text/html'

    async def read(args, config):
        calls.append(args['url'])
        return '已通过阅读代理读取网页：' + args['url'] + '\n测试网页正文'

    monkeypatch.setattr(ToolAnalyzer, '_fetch_url', fetch)
    monkeypatch.setattr(reader, 'open_web_page', read)
    config = SimpleNamespace()
    qq = asyncio.run(ToolAnalyzer(config)._analyze_url(url))
    store = KnowledgeStore(tmp_path / 'knowledge.sqlite3')
    source = store.create('desktop:owner', '', locator=url, enqueue=True, metadata={'import_url': True})
    ingestion.run_pending(store, config, max_jobs=1)
    saved = store.get('desktop:owner', source['id'])
    assert calls == [url, url]
    assert saved['job_status'] == 'done'
    assert saved['text'] == qq.knowledge_materials[0]['text']
    assert saved['coverage'] == 'reader_text_only'
    assert saved['metadata']['analysis']['read_level'] == 'partial_content'
