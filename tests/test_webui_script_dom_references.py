"""回归：渲染出的脚本里每一个 ``$('id')`` 都必须能在同一页 HTML 里找到对应元素。

背景（真实事故）：删掉「运行规则」卡片的开关、又删掉「主动互动门槛」卡片之后，
`collectProactivePolicy()` 里还留着 `Number($('proactiveGroupMinActivity').value)`。
元素没了，`$()` 返回 null，取 `.value` 直接抛 TypeError，于是点击「保存全部配置」
必然弹出「配置保存失败」——而且是运行时才暴露，静态语法检查（`node --check`）看不出来。

这个测试把「脚本引用的 id 与 DOM 对不上」这件事变成构建期就能发现的错误。
"""

from __future__ import annotations

import re

from atri_webui.page import render_index

# 这些 id 不在首屏 HTML 里，而是由脚本在运行时注入（表格行、动态表单等）。
RUNTIME_CREATED_IDS = {
    # 分档表的输入框：renderReplyStrategyRiers / renderReplyStrategyActivityTiers 注入
    "affectionTierRows",
    # 例外名单的表单控件：由 renderReplyStrategyExceptions 注入
    "replyExceptionRows",
    # 内容权重：由 loadProactive() 注入
    "proactiveWeights",
    "proactiveGroupWeights",
    # 通用回复设置：由 loadConfig() 注入
    "configForm",
}

# 既有的历史包袱：脚本里引用了、但当前页面并不生成的 id。它们都在
# 「元素不存在就 return」的分支里（或纯粹是被删页面留下的死代码），所以没有实际
# 报错；列在这里是为了让检查只对**新增**的失配报警。清理时应逐项从这个集合里删。
LEGACY_MISSING_IDS = {
    "evaluationSource",
    "memoryContextHint",
    "memoryContextSelector",
    "memoryImportantOnly",
    "memoryInfo",
    "memoryRecentOnly",
    "memoryRows",
    "memorySearch",
    "memorySort",
    "memoryTypeFilter",
    "qzoneAutoMeta",
    "qzoneBridgeAuth",
    "qzoneBrowserFeeds",
    "qzoneEnabled",
    "qzoneFeedConnection",
    "qzoneFeedCount",
    "qzoneFriendSearch",
    "summaryScheduleRows",
    "voicePreviewLanguage",
    "voicePreviewText",
}


def _static_ids(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


def _script_part(html: str) -> str:
    return html.rsplit("<script>", 1)[1].split("</script>", 1)[0]


def _script_id_references(script: str) -> set[str]:
    """收集脚本里所有 ``$('xxx')`` 形式的 id 引用。"""

    return {
        match.group(1)
        for match in re.finditer(r"""\$\(\s*['"]([A-Za-z0-9_\-]+)['"]\s*\)""", script)
    }


def _missing_ids(html: str, script: str | None = None) -> list[str]:
    referenced = _script_id_references(script if script is not None else _script_part(html))
    known = _static_ids(html) | RUNTIME_CREATED_IDS
    return sorted(referenced - known)


# ``$('id')`` 后面直接取属性、且 id 在当前页面不存在的写法——这就是"保存失败"的成因。
# 注意 ``$('id')?.value`` 是安全的（可选链），所以匹配时要求 ``)`` 后面直接跟 ``.``。
_DEREF_PATTERN = re.compile(
    r"""\$\(\s*['"]([A-Za-z0-9_\-]+)['"]\s*\)\s*\.\s*"""
    r"""(value|checked|innerHTML|textContent|files|disabled)"""
)

# 历史遗留在其他页面脚本里的同类写法。它们全都在「元素不存在就 return」的分支后面，
# 或属于已下线页面的死代码，所以没有实际报错。清理时应逐项移除。
LEGACY_UNSAFE_DEREFERENCES = {
    "memoryRows",
    "qzoneAutoMeta",
    "qzoneBrowserFeeds",
    "qzoneEnabled",
    "qzoneFeedConnection",
    "qzoneFeedCount",
    "voicePreviewLanguage",
    "voicePreviewText",
}


def test_no_new_null_unsafe_dereferences() -> None:
    """新增的 ``$('不存在的id').value`` 会让保存之类的操作直接抛异常。"""

    html = render_index()
    script = _script_part(html)
    known = _static_ids(html) | RUNTIME_CREATED_IDS

    new_unsafe = sorted(
        {
            match.group(1)
            for match in _DEREF_PATTERN.finditer(script)
            if match.group(1) not in known
        }
        - LEGACY_UNSAFE_DEREFERENCES
    )
    assert not new_unsafe, (
        "新增了「取属性前不判空」的写法，元素不存在时会抛 TypeError："
        + ", ".join(new_unsafe)
    )


def test_proactive_collect_uses_optional_chaining() -> None:
    """确认检查的判据可靠：可选链不算不安全。"""

    html = render_index()
    known = _static_ids(html) | RUNTIME_CREATED_IDS
    ghost = "definitelyNotAnElement"

    unsafe = {
        match.group(1)
        for match in _DEREF_PATTERN.finditer(f"$('{ghost}').value")
        if match.group(1) not in known
    }
    assert unsafe == {ghost}
    # 可选链不该被判为不安全
    optional = {
        match.group(1)
        for match in _DEREF_PATTERN.finditer(f"$('{ghost}')?.value")
        if match.group(1) not in known
    }
    assert optional == set()


def test_no_new_dangling_id_references() -> None:
    html = render_index()
    new_missing = sorted(set(_missing_ids(html)) - LEGACY_MISSING_IDS)
    assert not new_missing, (
        "脚本新增了对不存在元素的引用，运行时会抛 TypeError："
        + ", ".join(new_missing)
    )


def test_the_check_actually_catches_a_dangling_reference() -> None:
    """确认这个检查真的有效：故意加一个不存在的引用必须被抓出来。"""

    html = render_index()
    script = _script_part(html) + "\nconst broken = $('definitelyNotAnElement').value;\n"
    new_missing = sorted(set(_missing_ids(html, script)) - LEGACY_MISSING_IDS)

    assert new_missing == ["definitelyNotAnElement"]


def test_legacy_baseline_does_not_grow_silently() -> None:
    """基线里的每一项都必须仍然真的缺失；修好了就要从基线里删掉。"""

    html = render_index()
    still_missing = set(_missing_ids(html))
    stale = sorted(LEGACY_MISSING_IDS - still_missing)
    assert not stale, f"这些 id 已经能找到了，请从 LEGACY_MISSING_IDS 移除：{stale}"


def test_removed_proactive_controls_are_not_referenced_anywhere() -> None:
    """被删掉的控件不能在渲染结果里留下任何 ``$('id')`` 形式的引用。"""

    html = render_index()
    script = _script_part(html)

    for removed in (
        "proactiveGroupMinActivity",
        "proactiveGroupActiveDays",
        "proactiveGroupMinMessages",
        "proactiveGroupMinHours",
        "proactiveGroupMaxHours",
        "proactiveGroupDailyLimit",
        "proactivePrivateMinAffection",
        "proactivePrivateActiveDays",
        "proactivePrivateMinMessages",
        "proactiveTierSummary",
        "replyStrategyEnabled",
        "replyUnlistedMode",
        "replyActiveHoursStart",
        "replyActiveHoursEnd",
        "replyPreviewOut",
    ):
        assert f"$('{removed}')" not in script, removed


def test_save_flow_collects_both_tier_tables() -> None:
    """两个保存入口都要提交两张档位表，否则群聊档位会在保存时被写回旧值。"""

    html = render_index()

    assert "base.activity_tiers = collectReplyStrategyActivityTiers(" in html
    assert "base.tiers = collectAffectionTiers();" in html
    assert "base.affection_tiers = collectAffectionTiers();" in html


# ── 调用了被删掉的函数 ────────────────────────────────────────
# 真实事故：删掉「主动消息」页签时把 renderProactiveTierSummary() 一并删了，但
# loadReplyStrategy() 里还留着调用。该调用抛 ReferenceError，被同一个 try/catch
# 吞掉，于是它**后面**的群聊分档表与例外名单渲染全部不再执行 —— 界面表现为
# 「群聊分档行消失 + 保存失败」，而 node --check 与标记检查都看不出来。

_KNOWN_FUNCTIONS = {
    # 语言内建 / 浏览器 API / Node 全局 / 语法关键字，不在此文件里定义
    "String", "Number", "Boolean", "Object", "Array", "JSON", "Math", "Date",
    "RegExp", "Error", "TypeError", "Promise", "Map", "Set", "URLSearchParams",
    "parseInt", "parseFloat", "isNaN", "encodeURIComponent", "decodeURIComponent",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval", "fetch",
    "alert", "confirm", "requestAnimationFrame", "structuredClone", "queueMicrotask",
    # 本仓库里的共享工具
    "$", "api", "toast", "escapeHtml", "withButtonBusy", "runCoro", "SimpleNamespace",
    # 语法关键字/回调参数常见名，会被正则误当成调用
    "function", "if", "for", "while", "switch", "catch", "return", "typeof",
    "async", "await", "new", "delete", "void", "in", "of", "do", "else", "try",
    "action", "task", "render", "resolve", "reject", "callback", "handler", "reload",
    # CSS 颜色函数会出现在字符串里，被正则误抓
    "rgba", "rgb", "hsl", "url", "linear-gradient", "minmax", "repeat", "calc",
}


def _strip_comments(script: str) -> str:
    """去掉行注释与块注释，避免注释里出现的 ``foo()`` 被当成调用。"""

    without_block = re.sub(r"/\*.*?\*/", " ", script, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", " ", without_block)


def _defined_names(script: str) -> set[str]:
    """脚本里定义过的函数名 / 变量名。"""

    names = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", script))
    names |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", script))
    names |= set(re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", script))
    return names


def _called_names(script: str) -> set[str]:
    """脚本里被调用（``name(``）的名字，排除明显是方法调用的 ``.name(``。"""

    return {
        match.group(1)
        for match in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", script)
    }


def test_no_calls_to_undefined_functions() -> None:
    html = render_index()
    script = _strip_comments(_script_part(html))

    defined = _defined_names(script) | _KNOWN_FUNCTIONS
    # 只关心本项目自己的命名风格（驼峰且带小写开头），避免误报
    called = {name for name in _called_names(script) if name[0].islower()}
    undefined = sorted(called - defined)

    assert not undefined, (
        "调用了未定义的函数，运行时会抛 ReferenceError（并且常被 try/catch 吞掉）："
        + ", ".join(undefined)
    )


def test_the_undefined_call_check_actually_works() -> None:
    """确认检查有效：故意调用一个不存在的函数必须被抓出来。"""

    html = render_index()
    script = _strip_comments(_script_part(html)) + "\nconst x = totallyMissingFunction(1);\n"

    defined = _defined_names(script) | _KNOWN_FUNCTIONS
    called = {name for name in _called_names(script) if name[0].islower()}

    assert "totallyMissingFunction" in sorted(called - defined)


def test_deleted_proactive_summary_is_not_called() -> None:
    """已删除的 renderProactiveTierSummary 不能留下调用点。"""

    html = render_index()
    script = _strip_comments(_script_part(html))

    assert "function renderProactiveTierSummary" not in script
    assert "renderProactiveTierSummary(" not in script


def test_render_failures_are_isolated_per_block() -> None:
    """每一块渲染各自 try/catch，一块出错不再拖垮其它表格。"""

    html = render_index()

    assert "function renderPart(name, render)" in html
    for block in ("'用户分档'", "'群聊分档'", "'例外名单'"):
        assert f"renderPart({block}" in html, block


