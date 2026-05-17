from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"

    @property
    def sort_key(self) -> int:
        return {"P0": 0, "P1": 1, "P2": 2}[self.value]


class TaskStatus(str, Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    DOING = "doing"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"


class SubtaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    BLOCKED = "blocked"
    DONE = "done"


class Who(str, Enum):
    CLAUDE = "claude"
    HUMAN = "human"
    BOTH = "both"


class TaskType(str, Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"


class TaskIntent(str, Enum):
    RESUME = "resume"
    APPROVE = "approve"
    REJECT = "reject"
    PAUSE = "pause"


class Subtask(BaseModel):
    id: str
    title: str
    status: SubtaskStatus = SubtaskStatus.TODO
    blocking_reason: Optional[str] = None


class ConversationRole(str, Enum):
    HUMAN = "我"
    AI = "AI"
    # The daemon itself, surfacing meta-events the user needs to see in
    # Obsidian rather than only in logs/{id}.jsonl. Used for non-LLM
    # failures (provider_unavailable, etc.) where appending an [AI]
    # message would be misleading. `is_pending_placeholder_turn` ignores
    # SYSTEM entries — they don't suppress the next cycle.
    SYSTEM = "系统"

    @classmethod
    def _missing_(cls, value):
        # Back-compat: legacy files use "Human" for the human role.
        # When parser builds a ConversationRole from that string, route it
        # to HUMAN instead of raising ValueError.
        if value == "Human":
            return cls.HUMAN
        return None


class ConversationEntry(BaseModel):
    role: ConversationRole
    timestamp: datetime
    content: str


class Task(BaseModel):
    id: str
    title: str
    project: str = ""
    parent: Optional[str] = None
    priority: Priority = Priority.P1
    tags: list[str] = Field(default_factory=list)
    created: datetime
    updated: datetime
    auto_approve: bool = True
    depends_on: list[str] = Field(default_factory=list)
    instructions: str = ""
    who: Who = Who.CLAUDE
    when: Optional[str] = None
    type: Optional[TaskType] = None
    intent: Optional[TaskIntent] = None
    measure: str = ""
    why: str = ""
    source_files: list[str] = Field(default_factory=list)
    status_reason: Optional[str] = None
    subtasks: list[Subtask] = Field(default_factory=list)
    description: str = ""
    conversation: list[ConversationEntry] = Field(default_factory=list)
    source_path: Optional[str] = None  # tracks which file this was parsed from
    # Optional explicit LLM provider override. When set ("claude" or
    # "claude_cli"), LLMRouter dispatches this task to the named client
    # regardless of config default or tag-based escalation. Used when the
    # user wants to force a specific provider — e.g. running a one-off
    # mysql/dingtalk task on the API path even if claude_cli is the daemon
    # default. Tag-based escalation is the more common signal.
    provider: Optional[str] = None
    # Transient parser anomalies — non-fatal cases where _parse_body fell back
    # to a lenient interpretation. Orchestrator emits one `parser_warning` log
    # entry per item so silent-fail edge cases stay observable instead of
    # being deduced after the fact. Not persisted in frontmatter.
    parse_warnings: list[str] = Field(default_factory=list, exclude=True)


class LogEntry(BaseModel):
    ts: datetime = Field(default_factory=datetime.now)
    task_id: str
    action: str
    detail: str
    duration_ms: int = 0
    status: str = "success"
    tool: Optional[str] = None
    reason: Optional[str] = None


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Project(BaseModel):
    """A portfolio-level project card living at tasks/projects/<slug>.md.

    Distinct from Task: a Project does not move through columns and is not
    advanced by an LLM cycle. The Orchestrator reads it only to decide
    whether to advance tasks that reference it via Task.project.
    """

    slug: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    repo_path: Optional[str] = None
    priority: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    last_touched: Optional[datetime] = None
    title: str = ""
    body: str = ""
    source_path: Optional[str] = None
