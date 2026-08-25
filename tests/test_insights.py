from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from atri_qq_bot.insights.config import ALL_DIMENSIONS, InsightsConfig
import atri_qq_bot.insights.config as insights_config_module
from atri_qq_bot.insights.evaluation import EvaluationSample, EvaluationService
from atri_qq_bot.insights.evaluation import calculate_overall_score
from atri_qq_bot.insights.store import InsightsStore
from atri_qq_bot.insights.report import group_summary_html
from atri_qq_bot.insights.summary import (
    GroupSummaryService,
    _fallback_clusters,
    _fallback_report,
    _message_chunks,
    _activity_profile,
    _summary_prompt,
    _statistics,
)
from atri_webui.page import render_index


def test_insights_store_persists_scores_and_dashboard(tmp_path) -> None:
    store = InsightsStore(tmp_path / "insights.sqlite3")
    evaluation_id = store.create_evaluation(
        turn_id="turn-1",
        conversation_id="group:100",
        group_id="100",
        question="北京是中国的首都吗？",
        answer="是，北京是中国的首都。",
        context="资料：北京是中华人民共和国首都。",
        judge_model="deepseek-chat",
    )
    store.mark_evaluation_running(evaluation_id)
    store.complete_evaluation(
        evaluation_id,
        scores={
            "relevancy": {"score": 4.8, "reason": "直接回答", "metadata": {}},
            "faithfulness": {"score": 5.0, "reason": "上下文支持", "metadata": {}},
        },
        semantic_similarity=0.91,
        overall_score=4.9,
        issues=[],
    )

    detail = store.evaluation_detail(evaluation_id)
    dashboard = store.evaluation_dashboard(30)

    assert detail is not None
    assert detail["status"] == "completed"
    assert detail["scores"]["faithfulness"]["score"] == 5.0
    assert dashboard["counts"]["completed"] == 1
    assert dashboard["trend"][0]["average"] == 4.9
    assert dashboard["trend"][0]["minimum"] == 4.9
    assert dashboard["trend"][0]["maximum"] == 4.9


def test_dashboard_groups_model_types_and_delivery_results(tmp_path) -> None:
    store = InsightsStore(tmp_path / "model-types.sqlite3")
    for model_type, score in (("chat", 4.5), ("vision", 3.5), ("voice", 4.0)):
        evaluation_id = store.create_evaluation(
            turn_id=f"{model_type}-turn",
            conversation_id=f"{model_type}:1",
            group_id="",
            question="问题",
            answer="回答",
            context="",
            judge_model="test",
            model_type=model_type,
            model_name=f"{model_type}-model",
        )
        store.mark_evaluation_running(evaluation_id)
        store.complete_evaluation(
            evaluation_id,
            scores={"relevancy": {"score": score, "reason": "测试", "metadata": {}}},
            semantic_similarity=None,
            overall_score=score,
            issues=[],
        )
    store.record_delivery(event_id="chat-ok", model_type="chat", status="success")
    store.record_delivery(event_id="chat-fail", model_type="chat", status="failed", error="NapCat")
    store.record_delivery(event_id="voice-ok", model_type="voice", status="success")

    dashboard = store.evaluation_dashboard(30)
    grouped = {item["model_type"]: item for item in dashboard["model_types"]}
    assert grouped["vision"]["completed"] == 1
    assert grouped["voice"]["average"] == 4.0
    assert dashboard["delivery"]["success"] == 2
    assert dashboard["delivery"]["failed"] == 1
    delivery = {item["model_type"]: item for item in dashboard["delivery"]["by_model"]}
    assert delivery["chat"]["failed"] == 1


def test_delivery_dashboard_backfills_recent_logs_idempotently(tmp_path) -> None:
    log_root = tmp_path / "project"
    (log_root / "logs").mkdir(parents=True)
    now = datetime.now().astimezone().replace(microsecond=0)
    reply_lines = [
        {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "conversation_id": "private:1",
            "message_type": "private",
            "user_id": 1,
            "user_text": "普通问题",
            "voice_mode": "",
            "status": "delivered",
        },
        {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "conversation_id": "private:1",
            "message_type": "private",
            "user_id": 1,
            "user_text": "[图片]这是什么",
            "voice_mode": "",
            "status": "failed",
            "failure_reason": "timeout",
        },
    ]
    (log_root / "logs" / "reply-events.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in reply_lines), encoding="utf-8"
    )
    (log_root / "logs" / "voice-events.log").write_text(
        json.dumps({
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "delivered",
            "message_type": "private",
            "user_id": 1,
        }) + "\n",
        encoding="utf-8",
    )
    store = InsightsStore(tmp_path / "delivery.sqlite3", log_root=log_root)
    first = store.delivery_dashboard(2)
    second = store.delivery_dashboard(2)
    assert first["total"] == 3
    assert first["success"] == 2
    assert first["failed"] == 1
    assert {item["model_type"] for item in first["by_model"]} == {"chat", "vision", "voice"}
    assert second["total"] == first["total"]
    assert second["synced"] == 0


def test_dashboard_trend_exposes_distribution_and_local_change(tmp_path) -> None:
    store = InsightsStore(tmp_path / "trend.sqlite3")
    base = datetime.now(timezone.utc).replace(hour=1, minute=0, second=0, microsecond=0)
    for index, score in enumerate((4.8, 4.7, 3.1, 4.6)):
        item = store.create_evaluation(
            turn_id=f"trend-{index}", conversation_id="trend", group_id="", question="问题", answer="回答",
            context="", judge_model="test",
        )
        store.mark_evaluation_running(item)
        store.complete_evaluation(
            item,
            scores={"relevancy": {"score": score, "reason": "测试", "metadata": {}}},
            semantic_similarity=None, overall_score=score, issues=[],
        )
    dashboard = store.evaluation_dashboard(30)
    trend = dashboard["trend"]
    assert trend[0]["median"] == 4.65
    assert "p25" in trend[0] and "p75" in trend[0]
    assert "quality_index" in trend[0]
    assert "low_score_rate" in trend[0]


def test_overall_score_penalizes_critical_dimension_drop() -> None:
    balanced = calculate_overall_score({name: {"score": 4.5} for name in ALL_DIMENSIONS})
    risky = calculate_overall_score(
        {name: {"score": (1.0 if name == "accuracy" else 4.8)} for name in ALL_DIMENSIONS}
    )
    arithmetic = sum((1.0 if name == "accuracy" else 4.8) for name in ALL_DIMENSIONS) / len(ALL_DIMENSIONS)
    assert balanced == 4.5
    assert risky < arithmetic


def test_group_archive_and_summary_records_share_one_database(tmp_path) -> None:
    store = InsightsStore(tmp_path / "insights.sqlite3")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for index in range(3):
        assert store.add_group_message(
            message_key=f"100:{index}",
            group_id="100",
            user_id=str(index % 2),
            nickname=f"成员{index % 2}",
            content=f"关于 Python 评测系统的讨论 {index}",
            message_type="text",
            created_at=(now + timedelta(seconds=index)).isoformat(),
        )
    assert not store.add_group_message(
        message_key="100:0",
        group_id="100",
        user_id="0",
        nickname="重复",
        content="重复消息",
        message_type="text",
        created_at=now.isoformat(),
    )
    summary_id = store.create_summary(
        "100", (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=1)).isoformat(), "manual"
    )
    store.complete_summary(
        summary_id,
        title="Python 评测讨论",
        message_count=3,
        topics=[{"title": "评测系统"}],
        key_points=["使用异步任务"],
        statistics={"member_count": 2},
        content="# Python 评测讨论",
    )

    assert store.group_ids()[0]["messages"] == 3
    store.set_group_name("100", "评测交流群")
    assert store.group_ids()[0]["group_name"] == "评测交流群"
    assert len(store.group_messages("100", (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=1)).isoformat(), 100)) == 3
    assert store.summary_detail(summary_id)["topics"][0]["title"] == "评测系统"  # type: ignore[index]


def test_evaluation_worker_completes_without_blocking_caller(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        config = replace(
            InsightsConfig.from_env(),
            database_path=tmp_path / "worker.sqlite3",
            evaluation_enabled=True,
            judge_api_key="test-key",
            semantic_enabled=False,
            dimensions=ALL_DIMENSIONS,
        )
        store = InsightsStore(config.database_path)
        evaluation_id = store.create_evaluation(
            turn_id="turn-2",
            conversation_id="private:1",
            group_id="",
            question="给出一句问候",
            answer="你好！",
            context="",
            judge_model=config.judge_model,
        )

        async def fake_complete_json(self, **kwargs):
            return {
                "dimensions": {
                    key: {
                        "score": None if key == "faithfulness" else 4,
                        "reason": "测试理由",
                        "issues": [],
                    }
                    for key in ALL_DIMENSIONS
                },
                "issues": [],
            }

        monkeypatch.setattr(
            "atri_qq_bot.insights.evaluation.StructuredLLMClient.complete_json",
            fake_complete_json,
        )
        service = EvaluationService(store, config)
        await service.start()
        await asyncio.wait_for(service._queue.join(), timeout=2)
        await service.close()

        detail = store.evaluation_detail(evaluation_id)
        assert detail is not None
        assert detail["status"] == "completed"
        assert detail["scores"]["faithfulness"]["score"] is None
        assert detail["overall_score"] == 4.0

    asyncio.run(scenario())


def test_model_evaluation_mode_enqueues_manual_sample(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        config = replace(
            InsightsConfig.from_env(),
            database_path=tmp_path / "model.sqlite3",
            judge_api_key="test-key",
            semantic_enabled=False,
            system_evaluation_enabled=False,
            model_evaluation_enabled=True,
        )
        store = InsightsStore(config.database_path)

        async def fake_complete_json(self, **kwargs):
            return {"dimensions": {key: {"score": 4, "reason": "测试", "issues": []} for key in ALL_DIMENSIONS}}

        monkeypatch.setattr(
            "atri_qq_bot.insights.evaluation.StructuredLLMClient.complete_json",
            fake_complete_json,
        )
        service = EvaluationService(store, config)
        await service.start()
        evaluation_id = await service.enqueue(
            EvaluationSample(
                turn_id="webui-1",
                conversation_id="webui:model",
                group_id="",
                question="问题",
                answer="回答",
                source="model",
            )
        )
        await asyncio.wait_for(service._queue.join(), timeout=2)
        await service.close()
        detail = store.evaluation_detail(evaluation_id)
        assert detail is not None
        assert detail["source"] == "model"
        assert detail["status"] == "completed"

    asyncio.run(scenario())


def test_system_evaluation_can_be_disabled_without_affecting_model_mode(tmp_path) -> None:
    async def scenario() -> None:
        config = replace(
            InsightsConfig.from_env(),
            database_path=tmp_path / "modes.sqlite3",
            system_evaluation_enabled=False,
            model_evaluation_enabled=True,
        )
        service = EvaluationService(InsightsStore(config.database_path), config)
        await service.start()
        service.submit(EvaluationSample("1", "system:1", "", "问题", "回答"))
        await asyncio.sleep(0.05)
        assert service._queue.qsize() == 0
        await service.close()

    asyncio.run(scenario())


def test_reply_failure_is_persisted_as_failed_evaluation_without_judging(tmp_path) -> None:
    async def scenario() -> None:
        config = replace(
            InsightsConfig.from_env(),
            database_path=tmp_path / "reply-failure.sqlite3",
            evaluation_enabled=True,
            system_evaluation_enabled=True,
        )
        store = InsightsStore(config.database_path)
        service = EvaluationService(store, config)
        await service.start()
        service.submit_failure(
            EvaluationSample("turn-1", "private:1", "", "你好", ""),
            "backend unavailable",
        )
        await service.close()

        records = store.list_evaluations(status="failed", limit=10)["items"]
        assert len(records) == 1
        assert records[0]["answer"] == ""
        assert "backend unavailable" in records[0]["error"]

    asyncio.run(scenario())


def test_save_insights_env_persists_secret_without_exposing_it(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EVALUATION_API_KEY=old-key\n", encoding="utf-8")
    monkeypatch.setattr(insights_config_module, "PROJECT_ROOT", tmp_path)
    insights_config_module.save_insights_env({"EVALUATION_API_KEY": "new-key", "MODEL_EVALUATION_ENABLED": True})
    assert "EVALUATION_API_KEY=new-key" in env_file.read_text(encoding="utf-8")
    insights_config_module.save_insights_env({"EVALUATION_API_KEY": ""})
    assert "EVALUATION_API_KEY=new-key" in env_file.read_text(encoding="utf-8")
    assert InsightsConfig.from_env().public_dict()["judge_api_key"] == ""


def test_evaluation_judge_follows_active_chat_model(monkeypatch) -> None:
    monkeypatch.setenv("EVALUATION_USE_CHAT_MODEL", "true")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("OPENAI_MODEL", "qwen3:4b-instruct")
    monkeypatch.setenv("OPENAI_API_KEY", "ollama")
    monkeypatch.setenv("EVALUATION_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("EVALUATION_MODEL", "deepseek-chat")
    monkeypatch.setenv("EVALUATION_API_KEY", "invalid-legacy-key")
    config = InsightsConfig.from_env()
    assert config.judge_source == "active_chat_model"
    assert config.judge_base_url == "http://127.0.0.1:11434/v1"
    assert config.judge_model == "qwen3:4b-instruct"
    assert config.judge_api_key == "ollama"


def test_failed_evaluation_batch_retry_respects_source(tmp_path) -> None:
    async def scenario() -> None:
        config = replace(
            InsightsConfig.from_env(), database_path=tmp_path / "retry.sqlite3", semantic_enabled=False
        )
        store = InsightsStore(config.database_path)
        for source in ("system", "model"):
            item = store.create_evaluation(
                turn_id=source, conversation_id=source, group_id="", question="问题", answer="回答",
                context="", judge_model="test", source=source,
            )
            store.fail_evaluation(item, "测试失败")
        service = EvaluationService(store, config)
        await service.start()
        count = await service.retry_failed("model")
        assert count == 1
        assert store.failed_evaluation_ids("system")
        await service.close()

    asyncio.run(scenario())


def test_keyword_topic_fallback_and_statistics() -> None:
    now = datetime.now(timezone.utc).isoformat()
    messages = [
        {"user_id": "1", "nickname": "甲", "content": "Python 异步队列和 SQLite 评测", "created_at": now},
        {"user_id": "2", "nickname": "乙", "content": "Python 评测需要语义相似度", "created_at": now},
        {"user_id": "1", "nickname": "甲", "content": "晚上一起玩游戏副本", "created_at": now},
    ]
    chunks = _message_chunks(messages, size=1)
    clusters = _fallback_clusters(chunks, maximum=4)
    stats = _statistics(messages)

    assert sum(len(cluster) for cluster in clusters) == 3
    assert stats["message_count"] == 3
    assert stats["active_members"][0]["nickname"] == "甲"
    assert len(stats["hour_distribution"]) == 24


def test_group_summary_depth_scales_with_activity() -> None:
    quiet = _activity_profile({"message_count": 8, "member_count": 2, "messages_per_hour": 4})
    busy = _activity_profile({"message_count": 420, "member_count": 28, "messages_per_hour": 120})

    assert quiet["tier"] == "quiet"
    assert busy["tier"] == "very_active"
    assert busy["max_tokens"] > quiet["max_tokens"]
    assert busy["max_topics"] > quiet["max_topics"]


def test_group_summary_prompt_and_fallback_use_atri_voice() -> None:
    messages = [
        {"user_id": "1", "nickname": "甲", "content": "决定周五 20:00 发布版本", "created_at": "2026-08-21T12:00:00+00:00"},
        {"user_id": "2", "nickname": "乙", "content": "请 @甲 更新文档，链接 https://example.com", "created_at": "2026-08-21T12:05:00+00:00"},
    ]
    stats = _statistics(messages)
    profile = _activity_profile(stats)
    topics = [{"title": "版本发布", "message_count": 2, "keywords": [{"word": "版本", "count": 1}], "active_members": ["甲", "乙"], "samples": [m["content"] for m in messages]}]
    system, prompt = _summary_prompt("100", messages[0]["created_at"], messages[-1]["created_at"], topics, stats, profile=profile)
    fallback = _fallback_report("100", topics, stats, profile=profile, messages=messages)

    assert "亚托莉" in system
    assert "action_items" in prompt and "notable_quotes" in prompt and "timeline" in prompt
    assert "亚托莉" in fallback["summary"]
    assert "关键进展与待办" in fallback["summary"]
    assert "atri_view" in prompt and "member_highlights" in prompt
    assert fallback["topics"][0]["atri_view"]
    assert fallback["member_highlights"][0]["evaluation"]


def test_group_summary_html_report_contains_infographic_sections() -> None:
    html = group_summary_html(
        {
            "group_id": "100",
            "title": "亚托莉观察",
            "period_start": "2026-08-22T00:00:00+08:00",
            "period_end": "2026-08-22T23:59:00+08:00",
            "message_count": 188,
            "topics": [{"title": "版本发布", "summary": "讨论了发布时间", "message_count": 40}],
            "statistics": {
                "member_count": 31,
                "question_count": 6,
                "average_message_length": 18,
                "hour_distribution": [1] * 24,
                "activity_profile": {"label": "高活跃"},
                "report_sections": {"timeline": [{"period": "20:00", "message_count": 10}]},
            },
        }
    )
    assert "群聊总览和基本信息" in html
    assert "24H 活跃轨迹" in html
    assert "版本发布" in html
    assert "亚托莉的看法" in html
    assert "群友画像 · 活跃成员" in html
    assert "打印 / 保存 PDF" in html


def test_group_summary_service_generates_deterministic_fallback(tmp_path) -> None:
    async def scenario() -> None:
        config = replace(
            InsightsConfig.from_env(),
            database_path=tmp_path / "summary.sqlite3",
            judge_api_key="",
            summary_enabled=True,
            summary_min_messages=1,
            embedding_model="missing/local-model",
            embedding_local_only=True,
        )
        store = InsightsStore(config.database_path)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        for index, content in enumerate(("讨论 Python 异步评测", "SQLite 使用 WAL", "总结需要结构化标题")):
            store.add_group_message(
                message_key=f"200:{index}",
                group_id="200",
                user_id=str(index % 2),
                nickname=f"成员{index % 2}",
                content=content,
                message_type="text",
                created_at=(now + timedelta(seconds=index)).isoformat(),
            )
        service = GroupSummaryService(store, config)
        summary_id = await service.submit(
            "200",
            (now - timedelta(minutes=1)).isoformat(),
            (now + timedelta(minutes=1)).isoformat(),
        )
        await asyncio.gather(*tuple(service._jobs))

        detail = store.summary_detail(summary_id)
        assert detail is not None
        assert detail["status"] == "completed"
        assert detail["message_count"] == 3
        assert detail["statistics"]["clustering"] == "keyword-fallback"
        assert detail["content"].startswith("# 群 200")

    asyncio.run(scenario())


def test_group_summary_falls_back_when_judge_returns_auth_error(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        config = replace(
            InsightsConfig.from_env(),
            database_path=tmp_path / "summary-auth.sqlite3",
            judge_api_key="invalid-key",
            summary_enabled=True,
            summary_min_messages=1,
            embedding_model="missing/local-model",
            embedding_local_only=True,
        )
        store = InsightsStore(config.database_path)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        store.add_group_message(
            message_key="auth-fallback:1", group_id="auth-fallback", user_id="1", nickname="甲",
            content="讨论评测系统配置", message_type="text", created_at=now.isoformat(),
        )

        async def auth_error(self, **kwargs):
            raise RuntimeError("HTTP 401")

        monkeypatch.setattr("atri_qq_bot.insights.summary.StructuredLLMClient.complete_json", auth_error)
        service = GroupSummaryService(store, config)
        summary_id = await service.submit(
            "auth-fallback", (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=1)).isoformat()
        )
        await asyncio.gather(*tuple(service._jobs))
        detail = store.summary_detail(summary_id)
        assert detail is not None
        assert detail["status"] == "completed"
        assert "评测系统配置" in detail["content"]

    asyncio.run(scenario())


def test_webui_replaces_developer_tab_with_insights_panels() -> None:
    html = render_index()

    assert "showTab(event,'evaluation')" in html
    assert "MaiBot WebUI" in html
    assert "8001" in html
    assert "评测看板" in html
    assert "群聊总结" in html
    assert 'id="evaluationTrend"' in html
    assert 'id="evaluationTrendDetails"' in html
    assert 'id="evaluationModelProfile"' in html
    assert 'id="summaryGenerateButton"' in html
    assert "/api/evaluations/dashboard" in html
    assert "/api/group-summaries/generate" in html
    assert "/api/evaluations/retry-failed" in html
    assert "当前启用的聊天模型同时作为回复质量评测的 Judge" in html
    assert "两种评测方式与模型配置" not in html
    assert "模型评测：手动提交样本" not in html
    assert "showTab(event,'developer')" not in html
    # 开发者入口已迁入测试面板，实时日志则属于评测看板。
    assert html.index('id="test"') < html.index('id="developerLinks"') < html.index('id="evaluation"')
