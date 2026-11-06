"""Authenticated local core client. No platform SDK or model dependencies."""
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class IngressEvent:
    platform: str
    account_id: str
    conversation_id: str
    actor_id: str
    event_id: str
    text: str
    nickname: str = ''
    kind: str = 'private'

    def payload(self):
        return {'text': self.text, 'user_name': self.nickname, 'origin': {
            'platform': self.platform, 'account_id': self.account_id,
            'conversation_id': self.conversation_id, 'actor_id': self.actor_id,
            'event_id': self.event_id, 'kind': self.kind}}


class CoreClient:
    def __init__(self, base_url: str, api_key: str, *, timeout=120, transport=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'}):
            raise ValueError('核心地址必须是本机 HTTP 根地址')
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError('请先配置 CORE_API_KEY')
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    async def check(self):
        """Read-only authentication check; never invoke chat or start a core."""
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 5), trust_env=False,
                                         transport=self.transport) as client:
                response = await client.get(self.base_url + '/api/v1/capabilities',
                    headers={'X-ATRI-API-Key': self.api_key})
                response.raise_for_status()
                if response.json().get('ok') is not True:
                    raise ValueError('核心未就绪')
        except (httpx.HTTPError, ValueError):
            raise ValueError('ATRI 核心未连接或密钥不匹配；请检查核心服务、地址和 CORE_API_KEY') from None

    async def chat(self, event: IngressEvent):
        # Environment proxies must not route local credentials to another host.
        # No automatic retry: a timeout may mean generation already completed.
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False,
                                    transport=self.transport) as client:
            response = await client.post(self.base_url + '/api/v1/chat',
                headers={'X-ATRI-API-Key': self.api_key}, json=event.payload())
            response.raise_for_status()
            data = response.json()
        if not data.get('ok') or not isinstance(data.get('reply'), str) or not data['reply'].strip():
            raise ValueError('核心未返回完整回复')
        return data
