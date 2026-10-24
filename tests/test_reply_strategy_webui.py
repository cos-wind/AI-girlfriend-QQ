"""回复策略 WebUI 接口（对象合并、路由、页面元素）的回归测试。"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from atri_webui.server_parts import handler_core
from atri_webui.server_parts.handler_config import HandlerConfigMixin


class _FakeMemoryAdmin:
    def summary(self) -> dict[str, object]:
        return {
            "items": [
                {
                    "id": "private:10001",
                    "kind": "person",
                    "display_name": "主人",
                    "affection": 88.0,
                    "target": {"user_id": "10001"},
                },
                {
                    "id": "group:20001",
                    "kind": "group",
                    "display_name": "测试群",
                    "activity": 63.5,
                    "target": {"group_id": "20001"},
                },
                {
                    "id": "private:30003",
                    "kind": "person",
                    "display_name": "路人",
                    "affection": 20.0,
                    "target": {"user_id": "30003"},
                },
            ]
        }


def _fake_self():
    return SimpleNamespace(
        webui_state=SimpleNamespace(
            config=SimpleNamespace(owner_qqs=(10001,)),
            memory_admin=_FakeMemoryAdmin(),
        )
    )


def test_objects_merge_memory_and_policy_entries() -> None:
    policy = {
        "users": {"30003": {"mode": "deny", "name": "路人"}},
        "groups": {"40004": {"mode": "auto", "name": ""}},
    }

    objects = HandlerConfigMixin._reply_strategy_objects(_fake_self(), policy)

    by_id = {item["id"]: item for item in objects}
    assert set(by_id) == {"10001", "20001", "30003", "40004"}
    # 主人排在最前，其次是好感/活跃度更高的对象。
    assert objects[0]["id"] == "10001"
    assert by_id["10001"]["owner"] is True
    assert by_id["10001"]["kind"] == "user"
    assert by_id["20001"]["kind"] == "group"
    assert by_id["20001"]["activity"] == 63.5
    # 策略里手动添加、记忆里还没有的对象也要出现，并带上默认规则。
    assert by_id["40004"]["rule"]["mode"] == "auto"
    assert by_id["40004"]["name"] == "群 40004"
    assert by_id["30003"]["rule"]["mode"] == "deny"


def test_reply_strategy_routes_are_registered() -> None:
    get_source = inspect.getsource(handler_core.HandlerCoreMixin.do_GET)
    post_source = inspect.getsource(handler_core.HandlerCoreMixin.do_POST)

    assert "/api/reply-strategy" in get_source
    assert "/api/reply-strategy" in post_source
    assert "/api/reply-strategy/object" in post_source
    assert "/api/reply-strategy/preview" in post_source
    assert "/api/reply-strategy/reset-counters" in post_source
    assert "/api/qzone/bridge" in get_source
    assert "/api/qzone/bridge" in post_source


def test_advanced_page_renders_strategy_and_bridge_cards() -> None:
    from atri_webui.page.index import render_index

    html = render_index()

    for marker in (
        # 主动发起卡片（原「回复规则」卡片里的被动回复段已删除）
        'id="proactiveEnabled"',
        'id="proactiveGroupEnabled"',
        # 主动调度器的状态行挂在「主动发起」里，紧挨着控制它的勾选框。
        'id="proactiveFeatureState"',
        # 合并后的亲密度分档 + 群聊活跃度分档 + 例外名单
        'id="affectionTierRows"',
        'id="replyActivityTierRows"',
        'id="replyExceptionRows"',
        # 主动消息内容权重
        'id="proactiveWeights"',
        'id="proactiveGroupWeights"',
        'id="configForm"',
        # 本地服务卡片：Bridge 的运行状态统一显示在顶部「运行状态」，卡片里只有开关。
        'onclick="startQZoneBridge(this)"',
        'onclick="stopQZoneBridge(this)"',
    ):
        assert marker in html, marker


def test_proactive_tab_is_gone_and_group_mirrors_the_user_table() -> None:
    """「主动消息」只读页签已删除；群聊主动消息与用户分档同构，写在档位表里。"""

    from atri_webui.page.index import render_index

    html = render_index()

    # 只保留两个页签，只读摘要也一并删掉。
    assert "showTierPane('proactive')" not in html
    assert 'id="tierPaneProactive"' not in html
    assert 'id="proactiveTierSummary"' not in html
    assert "<h3>主动互动门槛</h3>" not in html
    # 群聊只有总开关，不再有单独一套门槛 / 间隔控件。
    assert 'id="proactiveGroupEnabled"' in html
    for removed in (
        'id="proactiveGroupMinHours"',
        'id="proactiveGroupMaxHours"',
        'id="proactiveGroupDailyLimit"',
        'id="proactiveGroupMinActivity"',
        'id="proactiveGroupActiveDays"',
        'id="proactiveGroupMinMessages"',
        'id="proactivePrivateMinAffection"',
        'id="proactivePrivateActiveDays"',
        'id="proactivePrivateMinMessages"',
    ):
        assert removed not in html, removed
    # 权重卡片移到了右侧，用紧凑变体。
    assert "weight-grid-compact" in html


def test_tier_tables_label_the_proactive_columns() -> None:
    """两张分档表都要标注哪几列属于主动消息，否则看不出那些数值是干什么的。"""

    from atri_webui.page.index import render_index

    html = render_index()

    # 用户分档：被动回复 / 主动发起两组表头。
    assert "被动回复（对方先说话时）" in html
    assert "主动发起（亚托莉先说话）" in html
    # 群聊分档：同样是两组表头，主动发起那组标注了"先在群里说话"。
    assert "被动回复（群消息触发时）" in html
    assert "主动发起（亚托莉先在群里说话）" in html
    # 两张表的主动侧都渲染同样的两个输入控件（间隔 + 每日上限）。
    for selector in ("tier-min-hours", "tier-max-hours", "tier-daily-limit"):
        assert html.count(selector) >= 2, selector


def test_reply_audience_thresholds_are_gone() -> None:
    """受众门槛已彻底移除：分档表的好感范围就是唯一的门槛入口。"""

    from atri_webui.page.index import render_index

    html = render_index()

    for removed in (
        "回复受众门槛",
        'id="replyPrivateMinAffection"',
        'id="replyPrivateActiveDays"',
        'id="replyPrivateMinMessages"',
        'id="replyGroupMinActivity"',
        'id="replyGroupActiveDays"',
        'id="replyGroupMinMessages"',
    ):
        assert removed not in html, removed
    # 这些字段也不该再被前端读写。
    assert "'private_min_affection'" not in html
    assert "replyStrategyCollectDefault" not in html


def test_redundant_reply_cards_are_gone() -> None:
    """「运行规则」和「档位预览」两张卡片已删除。

    运行规则 → 三个开关也不再要了（策略常开、全天不限、未列入名单按分档判断）；
    档位预览 → 表格本身就是对应关系，不需要再算一遍。
    """

    from atri_webui.page.index import render_index

    html = render_index()

    assert "档位预览" not in html
    assert 'id="replyPreviewOut"' not in html
    assert "previewReplyStrategy" not in html
    assert 'id="replyPreviewKind"' not in html
    assert "<h3>运行规则</h3>" not in html
    # 「运行规则」卡片的三个开关全删了：策略改为常开、未列入名单按分档判断、
    # 活跃时段全天不限。历史事故：脚本侧删干净了，但这里的标记一直留着，
    # 于是界面上摆着三个改了不生效的死控件（实测：元素存在、脚本引用为 0）。
    # 「未列入名单的对象」下拉当时被搬进了「回复规则」卡片，却从来没有任何脚本
    # 读写过它——所以它同样是死的，一并删除。要改这三项直接改 JSON。
    assert "$('replyStrategyEnabled')" not in html
    for removed_id in (
        "replyStrategyEnabled",
        "replyUnlistedMode",
        "replyActiveHoursStart",
        "replyActiveHoursEnd",
    ):
        assert f'id="{removed_id}"' not in html, removed_id
        assert f"$('{removed_id}')" not in html, removed_id
    assert "resetReplyStrategyCounters(this)" in html
    # 状态行本身也删了，用量改在重置后的 toast 里显示。
    assert 'id="replyStrategyState"' not in html


def test_proactive_preview_lives_in_the_chat_reply_test_panel() -> None:
    """主动消息预览属于测试面板：它是聊天回复测试的一个扩展项，不再单独占卡片。"""

    from atri_webui.page.index import render_index

    html = render_index()

    assert "主动消息预览（扩展）" in html
    # 预览控件现在是唯一的，不会再出现第二个入口。
    assert html.count('id="proactivePreviewOut"') == 1
    assert html.count('id="proactivePreviewScope"') == 1
    # 测试页会在切入时补齐内容类型下拉。
    test_tab = html.split("if(id==='test')", 1)[1].split("\n", 1)[0]
    assert "loadProactive()" in test_tab


def test_affection_tier_table_is_the_only_affection_table() -> None:
    """亲密度档位表只能存在一张，被动回复与主动发起的列挂在同一个 tbody 上。"""

    from atri_webui.page.index import render_index

    html = render_index()

    # 旧的两张重复表（回复侧「亲密度分档（私聊）」+ 主动侧「亲密度与频率」）都已消失。
    assert 'id="replyAffectionTierRows"' not in html
    assert 'id="proactiveTierRows"' not in html
    assert "亲密度与频率" not in html
    assert html.count('id="affectionTierRows"') == 1
    # 被动回复列：频率、冷却、长度都在同一张表里（冷却与每小时/每日上限曾经被
    # 移出界面，导致"聊到一定数量就不回了"没有任何可调的入口，现已做回表格）。
    assert "tier-group-reply" in html
    assert "tier-group-proactive" in html
    assert "tier-target-chars" in html
    assert "tier-max-parts" in html
    # 两个保存入口都提交整张表，避免只写一半。
    assert "collectAffectionTiers()" in html
    assert "saveReplyAndProactive(" in html


def test_tier_tables_no_longer_expose_frequency_caps() -> None:
    """「每小时上限 / 每日上限 / 冷却（秒）/ 连聊上限」已从两张分档表移除。

    回退原因：频率上限和"该不该回"叠在一起后，用户只会看到"聊到一半突然不回"，
    却找不到是哪一层拦的。现在分档只保留「目标字数 / 最多分条」作为软引导。
    """

    from atri_webui.page.index import render_index
    from atri_webui.page import script_strategy

    html = render_index()
    part = script_strategy.PART

    # 频率表头不再出现在「被动回复」列。
    for label in ("每小时上限", "冷却（秒）", "连聊上限"):
        assert html.count(f">{label}<") == 0, label
    # 每日上限：被动回复列已删，但主动发起列仍在（那是主动消息自己的参数）。
    assert html.count('class="tier-group-reply">每日上限<') == 0
    assert html.count('class="tier-group-proactive">每日上限<') == 2
    # 频率输入框不再渲染 / 收集。
    for cls in ("tier-per-hour", "tier-per-day", "tier-cooldown", "tier-continuation-max"):
        assert part.count(cls) == 0, (cls, part.count(cls))
    # 软引导仍在：目标字数 / 最多分条。
    assert "tier-target-chars" in part
    assert "tier-max-parts" in part


def test_tier_soft_length_fields_still_never_silently_zeroed() -> None:
    """目标字数/最多分条仍是软引导，空框必须回落到服务端原值（绝不写成 0）。"""

    from atri_webui.page import script_strategy

    part = script_strategy.PART

    for cls in ("tier-target-chars", "tier-max-parts"):
        assert f"replyStrategyCellNumberOrBase(row, '.{cls}'" in part, cls


def test_user_directory_no_longer_owns_chat_permission() -> None:
    """聊天权限已收回高级页：用户中心不应再出现"允许聊天"相关代码。"""

    from atri_webui.page.index import render_index

    html = render_index()

    for marker in (
        "userDirectoryChatMarkup",
        "saveUserDirectoryChat",
        "user-directory-chat",
    ):
        assert marker not in html, marker


def test_script_render_order_matches_the_coupled_chain() -> None:
    """脚本 PART 的顺序是有约束的，不能随便往中间插新脚本。

    这个仓库的脚本是"上一个文件以函数头 ``xxx() {`` 结尾、下一个文件接着写函数体"的
    链式写法。往中间插一个新脚本，后一个函数体就会被吞进前一个函数里，函数声明随之变成
    局部作用域——历史事故：回复策略脚本插入后，用户中心调用 ``ensureReplyStrategyLoaded``
    直接报"读取失败"。所以这里把顺序固定成快照。
    """

    import inspect
    import re

    from atri_webui.page import index as page_index

    source = inspect.getsource(page_index.render_index)
    order = re.findall(r"^\s+(SCRIPT_[A-Z_]+),?\s*$", source, re.M)

    assert order == [
        "SCRIPT_CORE",
        "SCRIPT_ACCOUNT",
        "SCRIPT_EVALUATION",
        "SCRIPT_SUMMARY",
        "SCRIPT_QQ_MUSIC",
        "SCRIPT_STATUS",
        "SCRIPT_MODELS",
        "SCRIPT_PROACTIVE",
        "SCRIPT_DIRECTORY",
        "SCRIPT_QZONE",
        "SCRIPT_SERVICES",
        "SCRIPT_STRATEGY",
        "SCRIPT_MEMORY",
        "SCRIPT_VOICE_TEST",
    ]


def test_account_script_boundaries_are_self_contained() -> None:
    """账号脚本插在 SCRIPT_CORE 与 SCRIPT_EVALUATION 之间，必须证明该边界是安全的。

    链式写法下"插在中间"本身有风险，所以这里把这个具体位置的边界条件钉住：

    * 前一个（SCRIPT_CORE）不能以函数头 ``{`` 结尾 —— 否则账号脚本会被吞进它的函数体，
      ``loadAccountBanner`` 等声明会变成局部作用域，横幅静默失效。
    * 账号脚本自身必须是自包含的 ``<script> ... </script>``。
    * 后一个（SCRIPT_EVALUATION）必须以一条完整声明开头，而不是接着写函数体。

    不追加到列表末尾的原因：最后一个 PART（SCRIPT_VOICE_TEST）以
    ``</script></body></html>`` 结尾，追加会落到 ``</html>`` 之后。
    """

    from atri_webui.page import script_account, script_core, script_evaluation

    core = script_core.PART.rstrip()
    account = script_account.PART
    evaluation = script_evaluation.PART

    assert not core.endswith("{"), "SCRIPT_CORE 变成函数头了，账号脚本会被吞进去"
    # 账号脚本必须是裸 JS：所有 script_*.py 的 PART 都拼在同一个 <script> 块里，
    # 自带标签会插入语法错误并提前关闭整块脚本（面板会变成"乱码 + 一堆报错"）。
    assert "<script>" not in account
    assert "</script>" not in account
    assert evaluation.lstrip().startswith("async function loadEvaluation("), (
        "SCRIPT_EVALUATION 不再以完整声明开头，说明它变成了上一个脚本的延续"
    )


def test_strategy_script_neighbours_are_self_contained() -> None:
    """回复策略两侧的 PART 不能再以函数头结尾，否则策略脚本又会被吞进函数体。"""

    from atri_webui.page import script_memory, script_qzone, script_services, script_strategy

    assert not script_qzone.PART.rstrip().endswith("{")
    assert not script_services.PART.rstrip().endswith("{")
    assert not script_strategy.PART.rstrip().endswith("{")
    assert script_memory.PART.lstrip().startswith("async function loadMemory() {")


def test_strategy_helpers_stay_at_top_level_in_rendered_script() -> None:
    """回复策略的辅助函数必须与用户中心的调用点处于同一（全局）作用域。"""

    from atri_webui.page.index import render_index

    html = render_index()

    assert "async function ensureReplyStrategyLoaded() {" in html
    # 用户中心会调用它们，必须定义在脚本顶层而不是某个函数体内。
    for helper in (
        "function replyStrategyRuleFor(",
        "function replyStrategyNormalizeMode(",
        "function replyStrategyRuleText(",
        "function replyStrategyFieldNumber(",
    ):
        assert helper in html, helper
        # 顶层定义前面不会紧跟缩进（缩进说明它被嵌进了别的块/函数里）。
        assert "\n" + helper in html, helper


def test_advanced_page_no_longer_owns_the_object_table() -> None:
    """对象级策略改由用户中心逐卡片设置，高级页只保留全局默认。"""

    from atri_webui.page.index import render_index

    html = render_index()

    assert 'id="replyStrategyRows"' not in html
    assert 'id="replyStrategyNewObject"' not in html
