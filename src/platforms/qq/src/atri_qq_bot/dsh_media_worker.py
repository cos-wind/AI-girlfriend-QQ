"""One-shot perception worker: reuse toolbox, never construct a chat engine."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from urllib.parse import urlsplit

MAX_INPUT = 34_000_000
VIDEO_HOSTS = {'b23.tv', 'www.b23.tv', 'bilibili.com', 'www.bilibili.com',
               'douyin.com', 'www.douyin.com', 'v.douyin.com', 'www.iesdouyin.com'}


def video_url(value):
    parsed = urlsplit(str(value))
    if (parsed.scheme != 'https' or parsed.hostname not in VIDEO_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('仅支持 HTTPS 的 B 站、抖音分享链接')
    return str(value)


async def analyze(payload, tools):
    if not tools.enabled:
        raise ValueError('资料分析工具已关闭')
    question = str(payload.get('question') or '')[:2000]
    if payload.get('kind') == 'images':
        images = payload.get('images')
        if not isinstance(images, list) or not 1 <= len(images) <= 3:
            raise ValueError('每次支持 1–3 张图片')
        # Validate the complete batch before any inference.
        decoded = []
        for item in images:
            data = base64.b64decode(item['data'], validate=True)
            if not data or len(data) > tools.vision_max_bytes:
                raise ValueError('图片为空或超过视觉读取上限')
            decoded.append(data)
        results = [await tools.analyze_image_upload(data, f'dsh:image:{i}', user_question=question)
                   for i, data in enumerate(decoded)]
    elif payload.get('kind') == 'video_url':
        results = [await tools.analyze_url_material(video_url(payload.get('url')), '')]
    else:
        raise ValueError('不支持的媒体类型')
    return {'ok': True, 'source': 'atri-toolbox', 'evidence_only': True,
            'results': [evidence(result) for result in results]}


def evidence(result):
    # Explicit projection: never serialize raw media, credentials or local paths.
    return {'kind': result.visual_kind, 'status': result.visual_status,
            'read_level': result.read_level,
            'findings': [str(v)[:12000] for v in result.findings[:12]],
            'limitations': [str(v)[:2000] for v in result.limitations[:12]],
            'video_evidence': [{k: material[k] for k in (
                'coverage', 'sample_positions_seconds', 'video_issues') if k in material}
                for material in result.knowledge_materials[:4]]}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('媒体请求过大')
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError('媒体请求必须是对象')
        from atri_shared.config import load_config
        from atri_bot.toolbox import ToolAnalyzer
        result = asyncio.run(analyze(payload, ToolAnalyzer(load_config())))
    except Exception:
        # Provider exceptions can contain API URLs/keys; keep those off MCP.
        result = {'ok': False, 'error': '媒体分析未完成，请检查分析开关、媒体大小和模型服务；不能据此猜测内容'}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
