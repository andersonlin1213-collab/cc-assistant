from __future__ import annotations

from pathlib import Path


class RulesLoader:
    """Loads the human-editable skills/rules.md file fresh on every call.

    Per the Completion Promise Pattern, every Orchestrator cycle re-reads
    rules so user edits take effect on the next cycle without restart.
    """

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def load(self) -> str:
        """Return the current rules.md content, or empty string if absent."""
        path = self.skills_dir / "rules.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
