"""Authenticated local plugin capabilities. No platform SDK or automatic retry."""
from urllib.parse import urlsplit

import httpx


class CapabilityClient:
    def __init__(self, url, token):
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/') or not token):
            raise ValueError('Plugin capabilities require authenticated loopback HTTP')
        self.url, self.token = url.rstrip('/'), token

    async def request(self, path, payload=None):
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            async with client.stream('GET' if payload is None else 'POST', self.url + path,
                    headers={'Authorization': 'Bearer ' + self.token}, json=payload) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 262144:
                        raise ValueError('Plugin response too large')
                import json
                return json.loads(content)

    async def schemas(self):
        return (await self.request('/capabilities'))['tools']

    async def execute(self, name, arguments):
        return (await self.request('/execute', {'name': name, 'arguments': arguments}))['result']
