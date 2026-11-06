"""Resolve public works, including JavaScript-loaded data, by exact work ID."""
from __future__ import annotations

import html
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse


def is_douyin_url(url: str) -> bool:
    host = (urlparse(url).hostname or '').lower()
    return any(host == root or host.endswith('.' + root) for root in ('douyin.com', 'iesdouyin.com'))


def share_target(url: str) -> tuple[str, str] | None:
    if not is_douyin_url(url):
        return None
    match = re.search(r'/(?:share/)?(video|note)/(\d+)(?:/|$)', urlparse(url).path)
    return (match[1], match[2]) if match else None


def public_item(text: str, item_id: str) -> dict:
    """Only accept the requested work, never recommended videos or layout metadata."""
    payloads = []
    try:
        payloads.append(json.loads(text))
    except ValueError:
        pass
    for pattern in (r'window\._ROUTER_DATA\s*=\s*', r'window\.__INITIAL_STATE__\s*=\s*'):
        match = re.search(pattern, text)
        if match:
            try:
                payloads.append(json.JSONDecoder().raw_decode(text[match.end():].lstrip())[0])
            except ValueError:
                pass
    render = re.search(r'<script\b[^>]*\bid=["\x27]RENDER_DATA["\x27][^>]*>(.*?)</script>', text, re.S)
    if render:
        try:
            payloads.append(json.loads(unquote(html.unescape(render[1]))))
        except ValueError:
            pass
    stack = list(payloads)
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if str(value.get('aweme_id') or value.get('awemeId') or '') == item_id:
                if isinstance(value.get('desc'), str) and (value['desc'].strip() or value.get('video')):
                    return value
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return {}


async def browser_public_item(kind: str, item_id: str) -> dict:
    """Read the requested public work after the site's normal JavaScript load."""
    import asyncio
    return await asyncio.wait_for(_browser_public_item(kind, item_id), timeout=30)


async def _browser_public_item(kind: str, item_id: str) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ValueError('缺少动态网页解析组件 playwright，请安装项目运行依赖') from exc

    if kind not in {'video', 'note'} or not item_id.isdecimal():
        raise ValueError('无效抖音作品地址')
    from atri_shared.runtime.paths import DATA_DIR
    runtime_root = DATA_DIR / 'runtime' / 'douyin-browser'
    runtime_root.mkdir(parents=True, exist_ok=True)
    # Node's os.tmpdir() does not fall back when Windows TEMP is unwritable.
    # Own both the profile and artifacts; never change the app's environment.
    with tempfile.TemporaryDirectory(prefix='read-', dir=runtime_root) as work_dir:
        return await _read_browser_public_item(async_playwright, kind, item_id, Path(work_dir))


async def _read_browser_public_item(async_playwright, kind: str, item_id: str, work_dir: Path) -> dict:
    import asyncio

    async with async_playwright() as driver:
        context = None
        launch_errors = []
        for channel in ('msedge', 'chrome', None):
            try:
                context = await driver.chromium.launch_persistent_context(
                    user_data_dir=str(work_dir / 'profile'),
                    artifacts_dir=str(work_dir / 'artifacts'),
                    channel=channel, headless=True, timeout=8000, locale='zh-CN',
                    env={**os.environ, 'TEMP': str(work_dir), 'TMP': str(work_dir),
                         'TMPDIR': str(work_dir)},
                )
                break
            except Exception as exc:
                detail = (str(exc).splitlines() or [type(exc).__name__])[0][:300]
                launch_errors.append(f'{channel or "chromium"}: {detail}')
                continue
        if context is None:
            raise ValueError('抖音网页解析浏览器启动失败：' + '；'.join(launch_errors))
        tasks = set()
        try:
            page = await context.new_page()
            found = {}

            async def read_response(response):
                if not is_douyin_url(response.url) or '/aweme/' not in response.url:
                    return
                try:
                    length = response.headers.get('content-length')
                    if length and int(length) > 3_000_000:
                        return
                    body = await response.body()
                    if len(body) <= 3_000_000:
                        item = public_item(body.decode('utf-8'), item_id)
                        if item:
                            found.update(item)
                except Exception:
                    pass

            def on_response(response):
                task = asyncio.create_task(read_response(response))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

            page.on('response', on_response)
            await page.goto(f'https://www.douyin.com/{kind}/{item_id}',
                            wait_until='domcontentloaded', timeout=20000)
            # The first document can be the site's JavaScript shell. Cookies and
            # redirects are handled by this isolated, disposable browser session.
            for _ in range(30):
                if found:
                    return found
                item = public_item(await page.content(), item_id)
                if item:
                    return item
                await asyncio.sleep(.5)
            return {}
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await context.close()
