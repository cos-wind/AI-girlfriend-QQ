from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import atri_webui.qzone_automation as qzone_automation
from atri_webui.qzone_automation import QZoneAutomation, QZoneAutomationStore, content_quality_issues, next_window_time, schedule_times


class _FakeAdmin:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def post(self, content: str, visibility: int = 1) -> dict[str, str]:
        self.posts.append(content)
        return {"tid": "test-tid"}


class _FakeInteractionAdmin:
    def __init__(self, feed_count: int = 1) -> None:
        self.comments: list[dict[str, str]] = []
        self.feed_count = feed_count

    def feeds(self, user_id: str, limit: int) -> dict[str, list[dict[str, object]]]:
        return {"feeds": [{"tid": f"feed-{index}", "content": f"动态 {index}", "liked": False, "abstime": index} for index in range(self.feed_count, 0, -1)]}

    def comment(self, payload: dict[str, str]) -> dict[str, str]:
        self.comments.append(payload)
        return {"ok": "true"}


def test_due_window_posts_pending_item_immediately(tmp_path, monkeypatch) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    item = store.content_add("一条待发布动态")
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    admin = _FakeAdmin()
    automation = QZoneAutomation(store, lambda: admin)
    settings = store.save_settings(
        {
            "enabled": True,
            "post_enabled": True,
            "post_mode": "window",
            "period_days": 1,
            "posts_per_period": 1,
            "post_start_hour": max(0, now.hour - 1),
            "post_end_hour": 23,
            "next_post_at": 0.0,
        }
    )

    slots = schedule_times(settings, now=now.timestamp())
    monkeypatch.setattr(qzone_automation.time, "time", lambda: slots[0] + 180)
    assert automation._post_if_due(store.settings()) == 1
    assert admin.posts == [item["content"]]
    assert store.next_content() is None


def test_dashboard_moves_to_next_period_after_quota(tmp_path) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    now = datetime.now().astimezone()
    store.save_settings(
        {
            "enabled": True,
            "post_enabled": True,
            "post_mode": "window",
            "period_days": 1,
            "posts_per_period": 1,
            "post_start_hour": max(0, now.hour - 1),
            "post_end_hour": min(24, now.hour + 1),
        }
    )
    store.log("post", tid="already-posted")
    automation = QZoneAutomation(store, lambda: _FakeAdmin())

    dashboard = automation.dashboard()
    assert dashboard["next_post"]["scheduled_at"] > datetime.now().timestamp() + 20 * 3600


def test_auto_comment_is_generated_by_atri_model(tmp_path) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    store.save_targets([{"user_id": "123", "nickname": "好友", "enabled_comment": True}])
    store.save_settings({"enabled": True, "comment_enabled": True, "comment_use_pool": True, "post_model_profile_id": "profile-1"})
    pool_item = store.comment_add("评论池草稿", source_tid="feed-1", source_user_id="123", source_content="旧动态")
    admin = _FakeInteractionAdmin(feed_count=1)
    calls: list[tuple[str, str]] = []

    def generate(prompt: str, profile_id: str) -> dict[str, str]:
        calls.append((prompt, profile_id))
        return {"content": "亚托莉生成的评论"}

    automation = QZoneAutomation(store, lambda: admin, comment_generator=generate)
    assert automation._interact(store.settings()) == (0, 1)
    assert admin.comments[0]["content"] == "亚托莉生成的评论"
    assert calls and calls[0][1] == "profile-1"
    assert store.comment_get(int(pool_item["id"]))["status"] == "used"


def test_auto_comment_only_scans_three_latest_feeds(tmp_path) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    store.save_targets([{"user_id": "123", "nickname": "好友", "enabled_comment": True}])
    store.save_settings({"enabled": True, "comment_enabled": True, "max_comments_per_run": 10})
    admin = _FakeInteractionAdmin(feed_count=5)
    calls: list[str] = []

    def generate(prompt: str, profile_id: str) -> dict[str, str]:
        calls.append(prompt)
        return {"content": "亚托莉评论"}

    automation = QZoneAutomation(store, lambda: admin, comment_generator=generate)
    assert automation._interact(store.settings()) == (0, 3)
    assert len(calls) == 3
    assert {item["tid"] for item in admin.comments} == {"feed-3", "feed-4", "feed-5"}


def test_window_posts_use_stable_random_slots_inside_even_buckets() -> None:
    settings = {
        "timezone": "Asia/Shanghai",
        "period_days": 1,
        "posts_per_period": 2,
        "post_start_hour": 9,
        "post_end_hour": 21,
    }
    now = datetime(2026, 8, 22, 8, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
    first = next_window_time(settings, now=now, posted_count=0)
    second = next_window_time(settings, now=now, posted_count=1)
    slots = schedule_times(settings, now=now)
    assert [first, second] == slots
    assert 2 * 3600 < second - first < 10 * 3600
    assert [first, second] == [next_window_time(settings, now=now, posted_count=index) for index in range(2)]


def test_window_catches_up_a_missed_earlier_slot() -> None:
    settings = {
        "timezone": "Asia/Shanghai",
        "period_days": 1,
        "posts_per_period": 2,
        "post_start_hour": 10,
        "post_end_hour": 23,
    }
    slots = schedule_times(settings, now=datetime(2026, 8, 23, 10, 0, tzinfo=timezone(timedelta(hours=8))).timestamp())
    now = slots[0] + 60

    assert next_window_time(settings, now=now, posted_count=0) == now


def test_due_generated_item_is_refreshed_for_actual_catchup_time(tmp_path, monkeypatch) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    preview_settings = {"timezone": "Asia/Shanghai", "period_days": 1, "posts_per_period": 2, "post_start_hour": 10, "post_end_hour": 23}
    slots = schedule_times(preview_settings, now=datetime(2026, 8, 23, 10, 0, tzinfo=timezone(timedelta(hours=8))).timestamp())
    first_slot, later_slot = slots
    now = first_slot + 180
    store.save_settings({
        "enabled": True,
        "post_enabled": True,
        "post_auto_generate": True,
        "period_days": 1,
        "posts_per_period": 2,
        "post_start_hour": 10,
        "post_end_hour": 23,
            "next_post_at": later_slot,
    })
    store.content_add(
        "旧的十点文案",
        generated_at=now - 600,
        scheduled_at=first_slot,
    )
    prompts: list[str] = []
    admin = _FakeAdmin()

    def generate(prompt: str, profile_id: str) -> dict[str, str]:
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"content": "按实际补发时刻重新生成的动态，内容与当前发布时刻保持一致。"}
        return {"content": "下一条动态会换一个观察角度，并保留具体的事实依据。"}

    monkeypatch.setattr(qzone_automation.time, "time", lambda: now)
    automation = QZoneAutomation(store, lambda: admin, post_generator=generate)

    assert automation._post_if_due(store.settings()) == 1
    assert admin.posts and len(admin.posts[0]) >= 20
    expected_time = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    assert prompts and expected_time in prompts[0]
    pending = store.next_content()
    assert pending is not None
    assert pending["scheduled_at"] == later_slot


def test_topic_prompt_adds_depth_angle_and_recent_content_deduplication() -> None:
    settings = {
        "timezone": "Asia/Shanghai",
        "posts_per_period": 2,
        "post_start_hour": 10,
        "post_prompt": "写一条动态",
        "topic_rotation": ["生活观察"],
    }
    prompt = qzone_automation.topic_prompt(
        settings,
        datetime(2026, 8, 23, 16, 30, tzinfo=timezone(timedelta(hours=8))).timestamp(),
        slot_index=1,
        recent_contents=["以前写过的阳光和海风。"],
    )

    assert "计划发布时间：2026-08-23 16:30" in prompt
    assert "本次切入角度：" in prompt
    assert "观察或问题" in prompt
    assert "以前写过的阳光和海风。" in prompt
    assert "禁止只堆阳光、海风、夜色、微笑等意象" in prompt


def test_delete_pending_item_reveals_next_generated_item(tmp_path) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    first = store.content_add("旧的待发布动态")
    store.save_settings({
        "enabled": True,
        "post_enabled": True,
        "post_auto_generate": True,
        "posts_per_period": 1,
        "post_start_hour": 0,
        "post_end_hour": 24,
    })

    def generate(prompt: str, profile_id: str) -> dict[str, str]:
        return {"content": "新的下一条动态，内容已经准备好了，等到合适的时间再发布。"}

    automation = QZoneAutomation(store, lambda: _FakeAdmin(), post_generator=generate)
    store.content_delete(int(first["id"]))
    next_item = automation.refresh_next_post()
    assert next_item is not None
    assert str(next_item["content"]).startswith("新的下一条动态")
    assert next_item["status"] == "pending"


def test_refresh_preserves_slot_until_timing_changes(tmp_path) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    store.save_settings({
        "enabled": True,
        "post_enabled": True,
        "posts_per_period": 2,
        "post_start_hour": 0,
        "post_end_hour": 24,
    })
    automation = QZoneAutomation(store, lambda: _FakeAdmin())
    before = automation.dashboard()["next_post"]["scheduled_at"]
    assert automation.dashboard()["next_post"]["scheduled_at"] == before
    # Only a timing edit invalidates the persisted schedule.
    store.save_settings({"post_start_hour": 1})
    assert store.settings()["next_post_at"] == 0.0


def test_scheduler_lease_blocks_duplicate_processes_and_expires(tmp_path, monkeypatch) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    now = 1_000.0
    monkeypatch.setattr(qzone_automation.time, "time", lambda: now)
    assert store.acquire_scheduler_lease("first", ttl=60)
    assert not store.acquire_scheduler_lease("second", ttl=60)
    monkeypatch.setattr(qzone_automation.time, "time", lambda: now + 91)
    assert store.acquire_scheduler_lease("second", ttl=60)


def test_content_quality_gate_rejects_template_and_recent_duplicate() -> None:
    assert content_quality_issues("阳光、海风、夜色、微笑，美好的一天。")
    assert content_quality_issues("一个具体观察带来一个明确观点，并且会提出新的问题。", ["一个具体观察带来一个明确观点，并且会提出新的问题。"])
    assert not content_quality_issues("我发现同一件小事在不同时间会有不同答案：这次我选择先验证，再下结论。")


def test_same_schedule_slot_is_published_only_once_across_processes(tmp_path, monkeypatch) -> None:
    """A scheduler lease timeout must never turn into two external posts."""
    database = tmp_path / "qzone.sqlite3"
    first_store = QZoneAutomationStore(database)
    second_store = QZoneAutomationStore(database)
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    settings = first_store.save_settings(
        {
            "enabled": True,
            "post_enabled": True,
            "post_auto_generate": False,
            "period_days": 1,
            "posts_per_period": 1,
            "post_start_hour": 9,
            "post_end_hour": 23,
        }
    )
    first_store.content_add("同一个发布时间槽位只能被发送一次，这条内容用于并发回归测试。")
    due_at = schedule_times(settings, now=now.timestamp())[0] + 180
    monkeypatch.setattr(qzone_automation.time, "time", lambda: due_at)

    start_barrier = threading.Barrier(2)
    posted: list[str] = []

    class BarrierAdmin:
        def post(self, content: str, visibility: int = 1) -> dict[str, str]:
            posted.append(content)
            return {"tid": f"tid-{len(posted)}"}

    automations = (
        QZoneAutomation(first_store, BarrierAdmin),
        QZoneAutomation(second_store, BarrierAdmin),
    )
    errors: list[BaseException] = []

    def publish(automation: QZoneAutomation) -> None:
        try:
            start_barrier.wait(timeout=2)
            automation._post_if_due(automation.store.settings())
        except BaseException as exc:  # surfaced below with both worker results
            errors.append(exc)

    workers = [threading.Thread(target=publish, args=(automation,)) for automation in automations]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)

    assert not errors
    assert len(posted) == 1


def test_quality_gate_rejects_unsupported_date_arithmetic() -> None:
    content = "距离中秋还有33天，这个日期提醒我们要提前准备。"
    facts = "当前时间：2026-08-24 12:00 Asia/Shanghai。没有取得可靠的新闻事实。"

    assert "包含事实依据未支持的数字或日期" in content_quality_issues(content, fact_context=facts)


def test_quality_gate_rejects_date_and_time_conflicts() -> None:
    scheduled = datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
    issues = content_quality_issues(
        "早安，刚起床才发现今天是8月25日，星期二。",
        fact_context="",
        scheduled_at=scheduled,
        timezone_value="Asia/Shanghai",
    )

    assert "正文日期与计划发布时间不一致" in issues
    assert "正文星期与计划发布时间不一致" in issues
    assert "正文时段与计划发布时间不一致" in issues


def test_quality_gate_rejects_invented_research_when_no_fact_source_exists() -> None:
    content = (
        "午后阳光照进来，我看到实验室新发的论文说："
        "量子纠错终于能在真实芯片上稳定运行了。"
    )

    issues = content_quality_issues(content, fact_context="")

    assert "包含未经事实依据支持的虚构亲历" in issues
    assert "包含没有可靠来源的现实事件陈述" in issues


def test_topic_prompt_rotates_writing_form_instead_of_fixed_template() -> None:
    settings = {
        "timezone": "Asia/Shanghai",
        "posts_per_period": 2,
        "post_start_hour": 9,
        "post_prompt": "写一条动态",
        "topic_rotation": ["日常趣事", "前沿科普"],
    }
    scheduled = datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
    first = qzone_automation.topic_prompt(settings, scheduled, slot_index=0)
    second = qzone_automation.topic_prompt(settings, scheduled, slot_index=1)

    assert "本次写作形态：" in first
    assert "本次写作形态：" in second
    assert first != second
    assert "先落到一个具体观察或问题" not in first


def test_fact_context_discards_calendar_and_keeps_recent_attributed_news() -> None:
    scheduled = datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
    raw = """搜索时间：2026-08-24 12:00:00 Asia/Shanghai
1. 标题：2026年日历与节日倒计时
   来源性质：一般网页/媒体摘要，需结合原文判断
   发布时间：Mon, 24 Aug 2026 01:00:00 GMT
   摘要：距离中秋还有33天。
   URL：https://www.rili.com.cn/calendar
2. 标题：某项公共服务发布新安排
   来源性质：媒体摘要
   发布时间：Sun, 23 Aug 2026 08:00:00 GMT
   摘要：主管部门公布了可核验的新安排，具体内容以原文为准。
   URL：https://www.gov.cn/example
"""

    result = qzone_automation.sanitize_qzone_fact_context(raw, scheduled)

    assert "距离中秋" not in result
    assert "某项公共服务发布新安排" in result
    assert "https://www.gov.cn/example" in result


def test_uncertain_external_send_consumes_slot_without_automatic_retry(tmp_path, monkeypatch) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    settings = store.save_settings(
        {
            "enabled": True,
            "post_enabled": True,
            "posts_per_period": 1,
            "post_start_hour": 9,
            "post_end_hour": 23,
        }
    )
    store.content_add("外部接口超时以后不应自动重复发送同一个槽位的动态。")
    due_at = schedule_times(settings, now=now.timestamp())[0] + 180
    monkeypatch.setattr(qzone_automation.time, "time", lambda: due_at)
    calls = 0

    class TimeoutAdmin:
        def post(self, content: str, visibility: int = 1) -> dict[str, str]:
            nonlocal calls
            calls += 1
            raise TimeoutError("response lost")

    automation = QZoneAutomation(store, TimeoutAdmin)
    try:
        automation._post_if_due(store.settings())
    except TimeoutError:
        pass

    assert automation._post_if_due(store.settings()) == 0
    assert calls == 1
    assert store.count_consumed_post_slots("2026-08-24") == 1


def test_quality_policy_migration_rejects_old_generated_draft_and_expands_topics(tmp_path) -> None:
    database = tmp_path / "qzone.sqlite3"
    store = QZoneAutomationStore(database)
    draft = store.content_add(
        "旧生成稿里带有未经核验的日期倒计时，迁移后不能继续自动发布。",
        generated_at=1_000.0,
        scheduled_at=2_000.0,
    )
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM qzone_settings WHERE key='post_diversity_v5_migrated'")
        db.execute(
            "UPDATE qzone_settings SET value_json=? WHERE key='topic_rotation'",
            (json.dumps(qzone_automation.LEGACY_TOPIC_ROTATION, ensure_ascii=False),),
        )

    migrated = QZoneAutomationStore(database)

    assert migrated.content_get(int(draft["id"]))["status"] == "rejected"
    topics = migrated.settings()["topic_rotation"]
    assert any("抽象乐子" in topic for topic in topics)
    assert any("前沿新闻" in topic for topic in topics)


def test_completed_period_previews_first_random_slot_of_next_period() -> None:
    settings = {
        "timezone": "Asia/Shanghai",
        "period_days": 1,
        "posts_per_period": 2,
        "post_start_hour": 9,
        "post_end_hour": 23,
    }
    now = datetime(2026, 8, 24, 15, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
    next_period = datetime(2026, 8, 25, 9, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
    expected = schedule_times(settings, now=next_period)[0]

    assert next_window_time(settings, now=now, posted_count=2) == expected


def test_scheduler_restores_missing_generated_preview_before_due(tmp_path, monkeypatch) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    now = datetime(2026, 8, 24, 15, 0, tzinfo=timezone(timedelta(hours=8))).timestamp()
    monkeypatch.setattr(qzone_automation.time, "time", lambda: now)
    store.save_settings(
        {
            "enabled": True,
            "post_enabled": True,
            "post_auto_generate": True,
            "posts_per_period": 1,
            "post_start_hour": 9,
            "post_end_hour": 23,
        }
    )
    store.log("post", tid="today-already-posted", content="今天已经发布过的动态")
    admin = _FakeAdmin()

    def generate(prompt: str, profile_id: str) -> dict[str, str]:
        return {"content": "下一条预览已经按未来的随机发布时间生成，页面现在可以直接看到正文。"}

    automation = QZoneAutomation(store, lambda: admin, post_generator=generate)
    result = automation.run_once()

    assert result["posted"] == 0
    assert admin.posts == []
    assert store.next_content() is not None
    assert store.next_content()["scheduled_at"] == next_window_time(store.settings(), now=now, posted_count=1)


def test_prepare_reuses_failed_fact_lookup_instead_of_querying_twice(tmp_path) -> None:
    store = QZoneAutomationStore(tmp_path / "qzone.sqlite3")
    store.save_settings({
        "post_enabled": True,
        "post_auto_generate": True,
        "topic_rotation": ["某个领域的前沿新闻与科普"],
    })
    calls = 0

    def facts(*args, **kwargs) -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError("fact timeout")

    automation = QZoneAutomation(
        store,
        lambda: _FakeAdmin(),
        post_generator=lambda *_: {"content": "信息很多不等于理解充分，先核验来源，再判断它和自己的关系。"},
        fact_context_provider=facts,
    )

    assert automation.prepare_next_generated() is not None
    assert calls == 1
