from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from atri_qq_bot.config import BotConfig
from atri_qq_bot.llm_tools.schema import TOOL_INSTRUCTION_PROMPT, available_tool_schemas
from atri_qq_bot.llm_tools.time_tool import get_current_time
from atri_qq_bot.llm_tools.tool_loop import append_tool_results
from atri_qq_bot.llm_tools.weather_tool import _location_candidates, format_weather_result
from atri_qq_bot.llm_tools.web_search_tool import parse_bing_news_rss, parse_news_rss
from atri_qq_bot.persona import AtriReplyEngine


def test_get_current_time_uses_shanghai_without_tzdata() -> None:
    reply = get_current_time(
        {"timezone": "Asia/Shanghai"},
        now=datetime(2026, 7, 4, 7, 21, 30, tzinfo=timezone.utc),
    )

    assert "2026-07-04 15:21:30" in reply
    assert "鏄熸湡鍏? in reply
    assert "Asia/Shanghai" in reply


def test_parse_bing_news_rss_strips_html_and_limits_results() -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss><channel>
      <item>
        <title>绗竴鏉℃柊闂?/title>
        <link>https://example.com/one</link>
        <pubDate>Sat, 04 Jul 2026 07:00:00 GMT</pubDate>
        <description><![CDATA[<b>鎽樿</b> &amp; 鏇村鍐呭]]></description>
      </item>
      <item>
        <title>绗簩鏉℃柊闂?/title>
        <link>https://example.com/two</link>
        <pubDate>Sat, 04 Jul 2026 06:00:00 GMT</pubDate>
        <description>绗簩鏉℃憳瑕?/description>
      </item>
    </channel></rss>"""

    results = parse_bing_news_rss(rss, max_results=1)

    assert results == [
        {
            "title": "绗竴鏉℃柊闂?,
            "url": "https://example.com/one",
            "published_at": "Sat, 04 Jul 2026 07:00:00 GMT",
            "summary": "鎽樿 & 鏇村鍐呭",
        }
    ]


def test_parse_google_news_rss_uses_the_same_structured_parser() -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss><channel><item>
      <title>涓€鏉℃渶鏂版秷鎭?- 绀轰緥濯掍綋</title>
      <link>https://news.google.com/rss/articles/example</link>
      <pubDate>Sat, 25 Jul 2026 05:00:00 GMT</pubDate>
      <description><![CDATA[<a href="https://example.com">鏌ョ湅鏉ユ簮</a>]]></description>
    </item></channel></rss>"""

    results = parse_news_rss(rss)

    assert results[0]["title"] == "涓€鏉℃渶鏂版秷鎭?- 绀轰緥濯掍綋"
    assert results[0]["published_at"] == "Sat, 25 Jul 2026 05:00:00 GMT"


def test_format_weather_result_includes_current_and_forecast_data() -> None:
    result = format_weather_result(
        "鍗佸牥",
        {
            "name": "鍗佸牥",
            "country": "涓浗",
            "admin1": "婀栧寳",
            "admin2": "鍗佸牥甯?,
            "timezone": "Asia/Shanghai",
        },
        {
            "timezone": "Asia/Shanghai",
            "current": {
                "time": "2026-07-25T14:30",
                "temperature_2m": 35.5,
                "apparent_temperature": 39.3,
                "relative_humidity_2m": 47,
                "precipitation": 0.0,
                "weather_code": 1,
                "cloud_cover": 21,
                "wind_speed_10m": 16.3,
            },
            "daily": {
                "time": ["2026-07-25", "2026-07-26"],
                "weather_code": [51, 96],
                "temperature_2m_max": [35.6, 34.4],
                "temperature_2m_min": [27.1, 25.3],
                "precipitation_probability_max": [24, 47],
            },
        },
    )

    assert "涓浗 婀栧寳 鍗佸牥甯?鍗佸牥" in result
    assert "褰撳墠锛氬ぇ鑷存櫞鏈楋紝35.5掳C锛屼綋鎰?39.3掳C" in result
    assert "2026-07-26锛氶浄鏆翠即灏忓啺闆癸紝25.3鈥?4.4掳C" in result
    assert "Open-Meteo" in result


def test_weather_location_candidates_fall_back_from_province_to_city() -> None:
    assert _location_candidates("婀栧寳鍗佸牥") == ["婀栧寳鍗佸牥", "鍗佸牥"]
    assert _location_candidates("婀栧寳鐪佸崄鍫板競") == ["婀栧寳鐪佸崄鍫板競", "鍗佸牥甯?, "鍗佸牥"]


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
    assert "褰撳墠鏃堕棿" in messages[1]["content"]


def test_voice_tool_is_exposed_only_when_tts_is_enabled() -> None:
    disabled = SimpleNamespace(
        llm_tools_enabled=True,
        web_search_enabled=False,
        voice_tts_enabled=False,
    )
    enabled = SimpleNamespace(
        llm_tools_enabled=True,
        web_search_enabled=False,
        voice_tts_enabled=True,
        voice_max_chars=120,
    )

    assert "speak_as_atri" not in {
        item["function"]["name"] for item in available_tool_schemas(disabled)
    }
    assert "speak_as_atri" in {
        item["function"]["name"] for item in available_tool_schemas(enabled)
    }


def test_weather_tool_is_exposed_with_web_search_tools() -> None:
    enabled = SimpleNamespace(
        llm_tools_enabled=True,
        web_search_enabled=True,
        web_search_max_results=5,
        voice_tts_enabled=False,
    )

    tool_names = {
        item["function"]["name"] for item in available_tool_schemas(enabled)
    }

    assert {"get_current_time", "get_weather", "search_web"} <= tool_names
    assert "涓嶈鐢ㄦ柊闂绘悳绱唬鏇垮ぉ姘旀暟鎹? in TOOL_INSTRUCTION_PROMPT


def test_voice_tool_prompt_requires_explicit_requests_in_groups() -> None:
    assert "鏄庣‘瑕佹眰鍙戦€佹垨鏀跺惉璇煶鏃讹紝蹇呴』璋冪敤 speak_as_atri" in TOOL_INSTRUCTION_PROMPT
    assert "缇よ亰閲屼笉鏂逛究寮€楹? in TOOL_INSTRUCTION_PROMPT
    assert "绂佹缂栭€? in TOOL_INSTRUCTION_PROMPT
    assert "绂佹鐢ㄦ瓕璇嶃€佸姩浣滄弿鍐欐垨闊充箰绗﹀彿鍋囪宸茬粡鍞辫繃" in TOOL_INSTRUCTION_PROMPT


def test_append_tool_results_allows_a_context_executor() -> None:
    messages: list[dict[str, Any]] = []
    calls: list[tuple[str, dict[str, Any]]] = []
    assistant_message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-voice",
                "type": "function",
                "function": {
                    "name": "speak_as_atri",
                    "arguments": '{"text":"鏅氬畨銆?,"emotion":"gentle"}',
                },
            }
        ],
    }

    async def execute(name: str, arguments: dict[str, Any], config: Any) -> str | None:
        calls.append((name, arguments))
        return "璇煶璇锋眰宸叉帴鍙椼€?

    executed = asyncio.run(
        append_tool_results(
            messages,
            assistant_message,
            assistant_message["tool_calls"],
            SimpleNamespace(llm_tool_max_calls=2),
            executor=execute,
        )
    )

    assert executed == 1
    assert calls == [("speak_as_atri", {"text": "鏅氬畨銆?, "emotion": "gentle"})]
    assert messages[-1]["content"] == "璇煶璇锋眰宸叉帴鍙椼€?


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
            return FakeResponse({"choices": [{"message": {"role": "assistant", "content": "鐜板湪鏄笅鍗堛€?}}]})

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = BotConfig(
        bot_qq=111111111,
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

    reply = asyncio.run(engine._reply_with_api("private:10001", "浠婂ぉ鍑犲彿", None))

    assert reply == "鐜板湪鏄笅鍗堛€?
    assert posted_payloads[0]["tools"]
    assert len(posted_payloads) == 2


def test_reply_with_api_supports_two_sequential_tool_rounds(monkeypatch) -> None:
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
            call_number = len(posted_payloads)
            if call_number <= 2:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": f"call-time-{call_number}",
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
            return FakeResponse(
                {"choices": [{"message": {"role": "assistant", "content": "鏌ュ畬浜嗐€?}}]}
            )

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
        llm_tool_max_calls=2,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine._reply_with_api("private:10001", "鍏堢‘璁ゆ椂闂村啀鍥炵瓟", None))

    assert reply == "鏌ュ畬浜嗐€?
    assert len(posted_payloads) == 3
    assert "tools" in posted_payloads[1]
    assert "tools" not in posted_payloads[2]


def test_reply_engine_captures_voice_tool_request(monkeypatch) -> None:
    posted = 0

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

        async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            nonlocal posted
            posted += 1
            if posted == 1:
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "voice",
                                            "type": "function",
                                            "function": {
                                                "name": "speak_as_atri",
                                                "arguments": '{"text":"鏅氬畨锛屽仛涓ソ姊︺€?,"emotion":"gentle","reason":"explicit_request"}',
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                )
            return FakeResponse(
                {"choices": [{"message": {"role": "assistant", "content": "宸茬粡鐢ㄨ闊宠鍟︺€?}}]}
            )

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
        voice_tts_enabled=True,
    )
    engine = AtriReplyEngine(config)

    asyncio.run(engine._reply_with_api("private:10001", "鐢ㄨ闊宠鏅氬畨", None))
    request = engine.consume_voice_request("private:10001")

    assert request is not None
    assert request.text == "鏅氬畨锛屽仛涓ソ姊︺€?
    assert request.emotion == "gentle"
    assert request.reason == "explicit_request"
    assert engine.consume_voice_request("private:10001") is None


def test_reply_probability_gate_hides_only_voice_tool(monkeypatch) -> None:
    posted_payloads: list[dict[str, Any]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "鏂囧瓧鍥炲"}}]}

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            posted_payloads.append(kwargs["json"])
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = BotConfig(
        bot_qq=111111111,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
        voice_tts_enabled=True,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(
        engine._reply_with_api(
            "private:10001",
            "浠婂ぉ杩囧緱鎬庝箞鏍?,
            None,
            allow_reply_voice=False,
        )
    )

    tool_names = {
        item["function"]["name"] for item in posted_payloads[0].get("tools", [])
    }
    assert reply == "鏂囧瓧鍥炲"
    assert "speak_as_atri" not in tool_names
    assert "get_current_time" in tool_names
