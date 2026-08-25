from __future__ import annotations

import atri_qq_bot.__main__ as entrypoint


def test_main_logs_and_stops_when_configuration_is_invalid(monkeypatch) -> None:
    calls: list[str] = []
    real_get_logger = entrypoint.logging.getLogger

    class FakeLogger:
        def info(self, *args, **kwargs) -> None:
            return None

        def warning(self, *args, **kwargs) -> None:
            return None

        def exception(self, *args, **kwargs) -> None:
            calls.append("exception")

    monkeypatch.setattr(entrypoint, "_acquire_bot_mutex", lambda: True)
    monkeypatch.setattr(entrypoint, "configure_project_logging", lambda: None)
    monkeypatch.setattr(
        entrypoint,
        "load_config",
        lambda: (_ for _ in ()).throw(ValueError("invalid config")),
    )
    monkeypatch.setattr(
        entrypoint.logging,
        "getLogger",
        lambda name=None: FakeLogger()
        if name == "atri.startup"
        else real_get_logger(name),
    )
    monkeypatch.setattr(
        entrypoint.asyncio,
        "run",
        lambda coroutine: calls.append("run"),
    )

    entrypoint.main()

    assert calls == ["exception"]
