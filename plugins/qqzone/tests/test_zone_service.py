from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from plugins.qqzone.zone_service import (
    BridgeSettings,
    QQZoneError,
    QQZoneService,
    _normalize_feed,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode()


class ZoneServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = QQZoneService(
            BridgeSettings(enabled=True, access_token="secret", base_url="http://127.0.0.1:5700")
        )

    def test_normalizes_feed_and_preserves_like_metadata(self) -> None:
        feed = _normalize_feed(
            {
                "tid": "feed-1",
                "uin": 123456,
                "nickname": "小明",
                "content": "  今天   很好  ",
                "createTime": {"time": 1700000000},
                "likenum": "3",
                "cmtnum": "1",
                "pic": [{"url": "a"}],
                "appid": "311",
                "typeid": "0",
                "likeUnikey": "u-key",
                "likeCurkey": "c-key",
            }
        )
        assert feed is not None
        self.assertEqual(feed.content, "今天 很好")
        self.assertEqual(feed.like_count, 3)
        self.assertEqual(feed.comment_count, 1)
        self.assertEqual(feed.image_count, 1)
        self.assertEqual(feed.abstime, 1700000000)
        self.assertEqual(feed.unikey, "u-key")

    def test_accepts_string_zero_retcode_and_sends_bearer_token(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: float) -> _Response:
            captured["authorization"] = request.headers.get("Authorization")  # type: ignore[attr-defined]
            captured["timeout"] = timeout
            return _Response({"status": "ok", "retcode": "0", "data": {"valid": True}})

        with patch("plugins.qqzone.zone_service.urlopen", fake_urlopen):
            result = self.service._sync_action("check_cookie", {})
        self.assertEqual(result, {"valid": True})
        self.assertEqual(captured["authorization"], "Bearer secret")

    def test_remote_bridge_is_rejected_by_default(self) -> None:
        service = QQZoneService(BridgeSettings(enabled=True, base_url="http://192.0.2.10:5700"))
        status = asyncio.run(service.status())
        self.assertFalse(status["connected"])
        self.assertIn("只允许本机", status["error"])

    def test_like_action_uses_cached_feed_metadata(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        async def action(name: str, params: dict[str, object]) -> dict[str, bool]:
            calls.append((name, params))
            return {"ok": True}

        self.service.action = action  # type: ignore[method-assign]
        asyncio.run(
            self.service.like_feed(
                {
                    "tid": "tid-1",
                    "user_id": "10001",
                    "abstime": 123,
                    "appid": 311,
                    "typeid": 0,
                    "unikey": "uk",
                    "curkey": "ck",
                }
            )
        )
        self.assertEqual(calls[0][0], "send_like")
        self.assertEqual(calls[0][1]["unikey"], "uk")

    def test_napcat_post_maps_visibility_to_ugc_right(self) -> None:
        service = QQZoneService(
            BridgeSettings(
                enabled=True,
                post_backend="napcat",
                napcat_base_url="http://127.0.0.1:3000",
            )
        )
        captured: dict[str, object] = {}

        def action_at(base_url: str, token: str, name: str, params: dict[str, object]) -> dict[str, str]:
            captured.update(base_url=base_url, token=token, name=name, params=params)
            return {"tid": "new-feed"}

        service._sync_action_at = action_at  # type: ignore[method-assign]
        result = asyncio.run(service.post_feed("hello", 1))
        self.assertEqual(captured["name"], "send_qzone_msg")
        self.assertEqual(captured["params"]["ugc_right"], 4)  # type: ignore[index]
        self.assertEqual(result["tid"], "new-feed")


if __name__ == "__main__":
    unittest.main()
