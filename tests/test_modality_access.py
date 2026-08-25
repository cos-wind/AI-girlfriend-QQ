from __future__ import annotations

from atri_qq_bot.runtime import modality_access


def test_voice_allowlist_accepts_an_allowed_member_or_allowed_group(
    tmp_path,
    monkeypatch,
) -> None:
    policy_path = tmp_path / "modality_access.json"
    monkeypatch.setattr(modality_access, "MODALITY_ACCESS_PATH", policy_path)
    modality_access.save_modality_access(
        {
            "version": 2,
            "voice_allowlist_enabled": True,
            "users": {"10001": {"name": "指定成员", "voice": True}},
            "groups": {"20001": {"name": "指定群聊", "voice": True}},
        }
    )

    assert modality_access.is_modality_allowed("10001", "voice") is True
    assert (
        modality_access.is_modality_allowed("90001", "voice", group_id="20001")
        is True
    )
    assert (
        modality_access.is_event_modality_allowed(
            {"message_type": "group", "group_id": "20001", "user_id": "90001"},
            "voice",
        )
        is True
    )
    assert (
        modality_access.is_event_modality_allowed(
            {"message_type": "group", "group_id": "29999", "user_id": "90001"},
            "voice",
        )
        is False
    )


def test_private_voice_access_does_not_inherit_a_group_permission(
    tmp_path,
    monkeypatch,
) -> None:
    policy_path = tmp_path / "modality_access.json"
    monkeypatch.setattr(modality_access, "MODALITY_ACCESS_PATH", policy_path)
    modality_access.save_modality_access(
        {
            "version": 2,
            "voice_allowlist_enabled": True,
            "groups": {"20001": {"name": "指定群聊", "voice": True}},
        }
    )

    assert (
        modality_access.is_event_modality_allowed(
            {"message_type": "private", "user_id": "90001"},
            "voice",
        )
        is False
    )

