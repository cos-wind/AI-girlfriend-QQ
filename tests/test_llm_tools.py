from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from atri_qq_bot.config import BotConfig
from atri_qq_bot.llm_tools.agent_protocol import (
    FINAL_ANSWER_TOOL_NAME,
    final_answer_from_call,
    has_unsupported_deferred_action,
    has_unverified_research_claim,
)
from atri_qq_bot.llm_tools.schema import TOOL_INSTRUCTION_PROMPT, available_tool_schemas
from atri_qq_bot.llm_tools.time_tool import get_current_time
from atri_qq_bot.llm_tools.tool_loop import append_tool_results
from atri_qq_bot.llm_tools.weather_tool import _location_candidates, format_weather_result
from atri_qq_bot.llm_tools.web_search_tool import (
    _bing_web_rss_url,
    _compact_research_query,
    _filter_results_by_domains,
    parse_arxiv_atom,
    parse_bing_news_rss,
    parse_github_repository_search,
    parse_news_rss,
)
from atri_qq_bot.llm_tools.web_page_tool import (
    _prefer_readable_source_url,
    extract_web_page_text,
    validate_public_web_url,
)
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


def test_parse_google_news_rss_uses_the_same_structured_parser() -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss><channel><item>
      <title>一条最新消息 - 示例媒体</title>
      <link>https://news.google.com/rss/articles/example</link>
      <pubDate>Sat, 25 Jul 2026 05:00:00 GMT</pubDate>
      <description><![CDATA[<a href="https://example.com">查看来源</a>]]></description>
    </item></channel></rss>"""

    results = parse_news_rss(rss)

    assert results[0]["title"] == "一条最新消息 - 示例媒体"
    assert results[0]["published_at"] == "Sat, 25 Jul 2026 05:00:00 GMT"


def test_bing_web_search_supports_general_visual_lookup_queries() -> None:
    url = _bing_web_rss_url("初音未来 绿色双马尾 耳机")

    assert "www.bing.com/search?" in url
    assert "format=rss" in url
    assert "%E5%88%9D%E9%9F%B3" in url


def test_domain_scoped_search_drops_results_from_unrelated_sites() -> None:
    results = [
        {"title": "官方仓库", "url": "https://github.com/example/project"},
        {"title": "转载", "url": "https://random.example/post"},
    ]

    assert _filter_results_by_domains(results, ["github.com"]) == [results[0]]


def test_research_search_parses_primary_arxiv_and_github_sources() -> None:
    atom = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>https://arxiv.org/abs/2608.00001</id>
        <title>Long Video Understanding Is Still Challenging</title>
        <published>2026-08-01T00:00:00Z</published>
        <summary>We evaluate temporal reasoning and report remaining limitations.</summary>
      </entry>
    </feed>"""
    github = {
        "items": [{
            "full_name": "example/long-video-benchmark",
            "html_url": "https://github.com/example/long-video-benchmark",
            "description": "Official benchmark repository",
            "updated_at": "2026-08-02T00:00:00Z",
            "language": "Python",
            "stargazers_count": 128,
        }]
    }

    arxiv_results = parse_arxiv_atom(atom)
    github_results = parse_github_repository_search(github)

    assert arxiv_results[0]["url"] == "https://arxiv.org/abs/2608.00001"
    assert "remaining limitations" in arxiv_results[0]["summary"]
    assert github_results[0]["title"] == "example/long-video-benchmark"
    assert "Stars：128" in github_results[0]["summary"]
    assert _compact_research_query(
        "Qwen2.5-VL long video temporal grounding benchmark 2026"
    ).startswith("Qwen2.5-VL")


def test_format_weather_result_includes_current_and_forecast_data() -> None:
    result = format_weather_result(
        "十堰",
        {
            "name": "十堰",
            "country": "中国",
            "admin1": "湖北",
            "admin2": "十堰市",
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

    assert "中国 湖北 十堰市 十堰" in result
    assert "当前：大致晴朗，35.5°C，体感 39.3°C" in result
    assert "2026-07-26：雷暴伴小冰雹，25.3–34.4°C" in result
    assert "Open-Meteo" in result


def test_weather_location_candidates_fall_back_from_province_to_city() -> None:
    assert _location_candidates("湖北十堰") == ["湖北十堰", "十堰"]
    assert _location_candidates("湖北省十堰市") == ["湖北省十堰市", "十堰市", "十堰"]


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

    assert {
        "get_current_time",
        "get_weather",
        "search_web",
        "open_web_page",
    } <= tool_names
    assert FINAL_ANSWER_TOOL_NAME not in tool_names
    assert "不要用新闻搜索代替天气数据" in TOOL_INSTRUCTION_PROMPT
    assert "视觉分析" in TOOL_INSTRUCTION_PROMPT
    assert "不要先问用户是否要搜索" in TOOL_INSTRUCTION_PROMPT


def test_final_answer_tool_is_exposed_only_for_opt_in_agent_protocol() -> None:
    enabled = SimpleNamespace(
        llm_tools_enabled=True,
        web_search_enabled=True,
        web_search_max_results=5,
        voice_tts_enabled=False,
        llm_agent_protocol_enabled=True,
        max_tokens=350,
    )

    tool_names = {
        item["function"]["name"] for item in available_tool_schemas(enabled)
    }

    assert FINAL_ANSWER_TOOL_NAME in tool_names


def test_agent_protocol_requires_real_actions_instead_of_promises() -> None:
    call = {
        "id": "final-1",
        "type": "function",
        "function": {
            "name": FINAL_ANSWER_TOOL_NAME,
            "arguments": '{"text":"目前仍然没有定论，我能确认的是研究仍在进行。"}',
        },
    }

    assert final_answer_from_call(call) == "目前仍然没有定论，我能确认的是研究仍在进行。"
    assert has_unsupported_deferred_action("你等等，我正在搜索，马上给你结果。")
    assert not has_unsupported_deferred_action("我搜索到的两条资料都认为目前尚无定论。")
    assert has_unverified_research_claim("我搜索到的资料说已经解决了。", set())
    assert not has_unverified_research_claim("我搜索到的资料说仍无定论。", {"search_web"})


def test_web_page_reader_extracts_article_text_and_blocks_private_hosts() -> None:
    page = """
    <html><head><title>研究进展</title><script>ignore()</script></head>
    <body><nav>导航栏</nav><main><h1>研究进展</h1>
    <p>这是第一段有效正文，介绍问题背景。</p>
    <p>这是第二段有效正文，说明当前仍然没有统一结论。</p>
    </main><footer>页脚</footer></body></html>
    """

    extracted = extract_web_page_text(page)

    assert "问题背景" in extracted
    assert "没有统一结论" in extracted
    assert "ignore" not in extracted
    assert "导航栏" not in extracted
    assert validate_public_web_url("https://example.com/research") == "https://example.com/research"
    assert validate_public_web_url("http://127.0.0.1:8787/private") == ""
    assert _prefer_readable_source_url("https://github.com/QwenLM/Qwen3") == (
        "https://raw.githubusercontent.com/QwenLM/Qwen3/HEAD/README.md"
    )


def test_voice_tool_prompt_requires_explicit_requests_in_groups() -> None:
    assert "明确要求发送或收听语音时，必须调用 speak_as_atri" in TOOL_INSTRUCTION_PROMPT
    assert "群聊里不方便开麦" in TOOL_INSTRUCTION_PROMPT
    assert "禁止编造" in TOOL_INSTRUCTION_PROMPT
    assert "禁止用歌词、动作描写或音乐符号假装已经唱过" in TOOL_INSTRUCTION_PROMPT


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
                    "arguments": '{"text":"晚安。","emotion":"gentle"}',
                },
            }
        ],
    }

    async def execute(name: str, arguments: dict[str, Any], config: Any) -> str | None:
        calls.append((name, arguments))
        return "语音请求已接受。"

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
    assert calls == [("speak_as_atri", {"text": "晚安。", "emotion": "gentle"})]
    assert messages[-1]["content"] == "语音请求已接受。"


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
        bot_qq=100000001,
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
    assert posted_payloads[0]["tool_choice"] == "auto"
    assert FINAL_ANSWER_TOOL_NAME not in {
        item["function"]["name"] for item in posted_payloads[0]["tools"]
    }
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
                {"choices": [{"message": {"role": "assistant", "content": "查完了。"}}]}
            )

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
        llm_tool_max_calls=2,
        llm_agent_max_tool_calls=2,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine._reply_with_api("private:10001", "先确认时间再回答", None))

    assert reply == "查完了。"
    assert len(posted_payloads) == 3
    assert "tools" in posted_payloads[1]
    assert "tools" not in posted_payloads[2]
    assert "tool_choice" not in posted_payloads[2]


def test_agent_loop_rejects_fake_search_and_executes_a_real_search(monkeypatch) -> None:
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

        async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            posted_payloads.append(kwargs["json"])
            call_number = len(posted_payloads)
            if call_number == 1:
                return FakeResponse({
                    "choices": [{"message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "bad-final",
                            "type": "function",
                            "function": {
                                "name": FINAL_ANSWER_TOOL_NAME,
                                "arguments": '{"text":"你等等，我正在搜索，马上给你结果。"}',
                            },
                        }],
                    }}]
                })
            if call_number == 2:
                return FakeResponse({
                    "choices": [{"message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "real-search",
                            "type": "function",
                            "function": {
                                "name": "search_web",
                                "arguments": '{"query":"神行百变 获取方式","mode":"web"}',
                            },
                        }],
                    }}]
                })
            return FakeResponse({
                "choices": [{"message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "good-final",
                        "type": "function",
                        "function": {
                            "name": FINAL_ANSWER_TOOL_NAME,
                            "arguments": (
                                '{"text":"现有资料显示神行百变需要按对应任务线获取；不同版本可能有差异。",'
                                '"sources":["https://example.com/guide"]}'
                            ),
                        },
                    }],
                }}]
            })

    async def fake_search(arguments: dict[str, Any], config: Any) -> str:
        assert arguments["query"] == "神行百变 获取方式"
        return "搜索结果：游戏官网攻略页给出了任务线说明。URL：https://example.com/guide"

    import httpx
    import atri_qq_bot.llm_tools.tool_loop as tool_loop

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(tool_loop, "search_web", fake_search)
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
        llm_agent_protocol_enabled=True,
        web_grounding_review_enabled=False,
    )
    engine = AtriReplyEngine(config)

    reply = asyncio.run(engine._reply_with_api("private:10001", "神行百变怎么获得", None))

    assert reply.startswith("现有资料显示")
    assert len(posted_payloads) == 3
    assert posted_payloads[0]["tool_choice"] == "required"
    assert any(
        message.get("role") == "tool" and message.get("name") == "search_web"
        for message in posted_payloads[2]["messages"]
    )


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
                                                "arguments": '{"text":"晚安，做个好梦。","emotion":"gentle","reason":"explicit_request"}',
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                )
            return FakeResponse(
                {"choices": [{"message": {"role": "assistant", "content": "已经用语音说啦。"}}]}
            )

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    config = BotConfig(
        bot_qq=100000001,
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

    asyncio.run(engine._reply_with_api("private:10001", "用语音说晚安", None))
    request = engine.consume_voice_request("private:10001")

    assert request is not None
    assert request.text == "晚安，做个好梦。"
    assert request.emotion == "gentle"
    assert request.reason == "explicit_request"
    assert engine.consume_voice_request("private:10001") is None


def test_reply_probability_gate_hides_only_voice_tool(monkeypatch) -> None:
    posted_payloads: list[dict[str, Any]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "文字回复"}}]}

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
        bot_qq=100000001,
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
            "今天过得怎么样",
            None,
            allow_reply_voice=False,
        )
    )

    tool_names = {
        item["function"]["name"] for item in posted_payloads[0].get("tools", [])
    }
    assert reply == "文字回复"
    assert "speak_as_atri" not in tool_names
    assert "get_current_time" in tool_names
