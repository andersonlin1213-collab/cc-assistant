import os
from pathlib import Path


def test_config_loads_defaults(monkeypatch, tmp_path):
    """Config should have sensible defaults when no .env exists.

    Two layers of `.env` lookup must be neutralised, otherwise the repo's
    actual .env (which ships with `LLM_PROVIDER=claude_cli` so the daemon
    doesn't burn API tokens by default) silently overrides the code-level
    defaults this test is meant to verify:

    1. `dotenv.load_dotenv()` at the top of `src.config` walks up from
       *the calling file's location* (`src/config.py`) — not cwd — so
       chdir alone doesn't help. Patch `dotenv.load_dotenv` to a no-op
       and reload `src.config` so the patched function is re-bound.
    2. pydantic-settings' `env_file=".env"` resolves relative to cwd —
       handle that with `monkeypatch.chdir(tmp_path)`.
    """
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.chdir(tmp_path)
    for key in ["LLM_PROVIDER", "TASKS_DIR", "LOGS_DIR", "SKILLS_DIR"]:
        monkeypatch.delenv(key, raising=False)

    import importlib
    import src.config
    importlib.reload(src.config)
    from src.config import config

    assert config.llm_provider == "claude"
    assert config.tasks_dir == Path("tasks")
    assert config.logs_dir == Path("logs")
    assert config.skills_dir == Path("skills")


def test_config_reads_env(monkeypatch):
    """Config should read values from environment variables."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("TASKS_DIR", "/tmp/my_tasks")
    monkeypatch.setenv("LOGS_DIR", "/tmp/my_logs")
    monkeypatch.setenv("SKILLS_DIR", "/tmp/my_skills")

    import importlib
    import src.config
    importlib.reload(src.config)
    from src.config import config

    assert config.llm_provider == "openai"
    assert config.tasks_dir == Path("/tmp/my_tasks")
    assert config.logs_dir == Path("/tmp/my_logs")
    assert config.skills_dir == Path("/tmp/my_skills")


def test_escalate_tags_set_parses_csv_with_whitespace():
    """`escalate_tags_set` is the canonical accessor for LLMRouter wiring;
    a user .env line `ESCALATE_TAGS=db, mysql , grafana,` (extra spaces and
    trailing comma) must parse cleanly into a 3-element frozenset."""
    from src.config import Config
    cfg = Config(escalate_tags="db, mysql , grafana,")
    assert cfg.escalate_tags_set == frozenset({"db", "mysql", "grafana"})


def test_escalate_tags_set_default():
    """Default value matches the original LLMRouter constant — backward
    compatible behavior for users who never set the env var."""
    from src.config import Config
    cfg = Config()
    assert cfg.escalate_tags_set == frozenset(
        {"db", "mysql", "wecom", "dingtalk", "api"}
    )
