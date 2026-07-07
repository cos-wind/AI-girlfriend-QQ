from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from atri_qq_bot.config import BotConfig
from atri_qq_bot.llm_tools.time_tool import get_current_time
from atri_qq_bot.llm_tools.tool_loop import append_tool_results
from atri_qq_bot.llm_tools.web_search_tool import parse_bing_news_rss
from atri_qq_bot.persona import AtriReplyEngine


def test_get_current_time_uses_shanghai_without_tzdata() -> None:
    reply = get_current_time(
        {"timezone": "Asia/Shanghai"},
        now=datetime(2026, 7, 4, 7, 21, 30, tzinfo=timezone.utc),
    )

    assert "2026-07-04 15:21:30" in reply
    assert "星期六" in reply
    assert "Asia/Shanghai" in reply


def test_parse_bing_news_rss_strips_html_and_limits_results() -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss><channel>
      <item>
        <title>第一条新闻</title>
        <link>https://example.com/one</link>
        <pubDate>Sat, 04 Jul 2026 07:00:00 GMT</pubDate>
        <description><![CDATA[<b>摘要</b> &amp; 更多内容]]></description>
      </item>
      <item>
        <title>第二条新闻</title>
        <link>https://example.com/two</link>
        <pubDate>Sat, 04 Jul 2026 06:00:00 GMT</pubDate>
        <description>第二条摘要</description>
      </item>
    </channel></rss>"""

    results = parse_bing_news_rss(rss, max_results=1)

    assert results == [
        {
            "title": "第一条新闻",
            "url": "https://example.com/one",
            "published_at": "Sat, 04 Jul 2026 07:00:00 GMT",
            "summary": "摘要 & 更多内容",
        }
    ]


def test_append_tool_results_executes_current_time() -> None:
    messages: list[dict[str, Any]] = []
    assistant_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-time",
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "arguments": '{"timezone":"Asia/Shanghai"}',
                },
            }
        ],
    }

    executed = asyncio.run(
        append_tool_results(
            messages,
            assistant_message,
            assistant_message["tool_calls"],
            SimpleNamespace(llm_tool_max_calls=2),
        )
    )

    assert executed == 1
    assert messages[0]["role"] == "assistant"
    assert messages[1]["role"] == "tool"
    assert messages[1]["name"] == "get_current_time"
    assert "当前时间" in messages[1]["content"]


def test_reply_with_api_runs_tool_call_loop(monkeypatch) -> None:
    posted_payloads: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> FakeResponse:
            posted_payloads.append(json)
            if len(posted_payloads) == 1:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call-time",
                                            "type": "function",
                                            "function": {
                                                "name": "get_current_time",
                                                "arguments": '{"timezone":"Asia/Shanghai"}',
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                )
            assert any(message.get("role") == "tool" for message in json["messages"])
            return FakeResponse({"choices": [{"message": {"role": "assistant", "content": "现在是下午。"}}]})

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = BotConfig(
        bot_qq=3380609082,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine._reply_with_api("private:10001", "今天几号", None))

    assert reply == "现在是下午。"
    assert posted_payloads[0]["tools"]
    assert len(posted_payloads) == 2
