"""Do not put fake test questions into the user's persistent usage history."""

import pytest

from agents.supervisor import usage_log


@pytest.fixture(autouse=True)
def disable_persistent_usage_by_default(monkeypatch):
    original = usage_log.load_config
    def config():
        return {**original(), "usage_logging": {"enabled": False}}
    monkeypatch.setattr(usage_log, "load_config", config)
