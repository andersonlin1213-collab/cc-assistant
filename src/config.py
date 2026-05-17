from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    # LLMRouter escalates a task to the API client when any of the task's
    # tags appear in this set — those tags signal the task needs a custom
    # cc-assistant tool (DatabaseTool, NotifierTool, etc.) which the
    # claude_cli subprocess can't reach. Comma-separated string in .env;
    # accessed as a frozenset via `escalate_tags_set`. Add a tag here when
    # introducing a new custom tool whose use should force the API path.
    escalate_tags: str = "db,mysql,wecom,dingtalk,api"

    # Database
    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = ""

    # WeChat
    wechat_webhook_url: str = ""

    # Obsidian
    obsidian_vault_name: str = "cc-assistant"
    # Whether `cc-assistant run` warns if the Obsidian desktop process
    # isn't running. Defaults False — the mobile-first workflow this
    # project optimizes for explicitly does NOT keep the desktop app open
    # (Obsidian Sync runs from phone alone). The warning was actionable
    # only for the original desktop-driven flow; in current usage it's
    # noise the user has to filter out on every restart. Set True in .env
    # if you really do want a desktop liveness check.
    obsidian_check_process: bool = False

    # Paths
    tasks_dir: Path = Path("tasks")
    logs_dir: Path = Path("logs")
    skills_dir: Path = Path("skills")

    # Dispatcher
    poll_interval_minutes: int = 30
    # How long the watcher waits after the LAST save event for a file
    # before firing a cycle. Each new save resets the timer, so this is
    # really "min idle time before we believe the user is done editing."
    #
    # Tuned for the mobile-first workflow: Obsidian Sync from a phone
    # uploads partial states every few seconds while the user is still
    # typing (IME confirm pauses, thinking, deleting). 5/7 dogfood saw
    # the daemon firing on a half-typed `你帮我查` and the AI replying
    # to the garbled fragment instead of the user's full intent. 15s
    # is the dialed-in middle ground after walking 2 → 10 → 30 → 15:
    # short enough that desktop responses don't feel sluggish, long
    # enough to absorb realistic IME / thinking pauses. Tune via
    # DEBOUNCE_SECONDS in .env if your typing speed differs.
    debounce_seconds: float = 15.0

    @property
    def escalate_tags_set(self) -> frozenset[str]:
        """Parse the comma-separated escalate_tags string into a frozenset.
        Empty entries and surrounding whitespace are dropped."""
        return frozenset(
            t.strip() for t in self.escalate_tags.split(",") if t.strip()
        )


config = Config()
