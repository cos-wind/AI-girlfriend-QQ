"""Platform identities are namespaced; remote clients cannot select owner scope."""
from dataclasses import dataclass
from hashlib import sha256
import json

from .application.contracts import ConversationTurnRequest


def _field(origin, key):
    value = origin.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 240 or '\x00' in value:
        raise ValueError(f'origin.{key} 格式错误')
    return value.strip()


def _key(*parts):
    # JSON framing avoids collisions between identifiers containing separators.
    return sha256(json.dumps(parts, ensure_ascii=False).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class PlatformTurn:
    request: ConversationTurnRequest
    event_key: str


def platform_turn(origin: dict, text: str, nickname: str) -> PlatformTurn:
    if not isinstance(origin, dict):
        raise ValueError('origin 必须是对象')
    platform, account, thread, actor, event = (
        _field(origin, k) for k in ('platform', 'account_id', 'conversation_id', 'actor_id', 'event_id'))
    if platform not in {'qq', 'wechat', 'wechat-desktop', 'bilibili', 'douyin'}:
        raise ValueError('不支持的接入平台')
    kind = origin.get('kind', 'private')
    if kind not in {'private', 'group'}:
        raise ValueError('origin.kind 格式错误')
    prefix = 'group:' if kind == 'group' else ''
    conversation = prefix + f'platform:{platform}:conversation:' + _key(account, kind, thread)
    profile = f'platform:{platform}:person:' + _key(account, actor)
    event_key = _key(platform, account, kind, thread, actor, event)
    request = ConversationTurnRequest(
        turn_id=event_key, conversation_id=conversation, profile_id=profile,
        kind=kind, user_text=text, nickname=nickname, actor_id=actor)
    return PlatformTurn(request, event_key)
