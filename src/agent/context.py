from __future__ import annotations

from src.agent.llm.types import Message
from src.models import Task


_SYSTEM_AGENT_INSTRUCTIONS = """\
You are an autonomous AI agent processing one task per cycle. The user maintains
the task's status by editing a Markdown file; you respond by appending to its
conversation thread and (when applicable) by signaling completion or blocking.

Decide the next concrete action and use the available tools. Tools include local
file operations and shell execution; use them as needed.

Two control tools govern the task lifecycle — call them at the END of your work:
  - `mark_complete(reason)`: the task is done. The system will move it to done/
    (or review/ if auto_approve is false).
  - `mark_blocked(reason)`: you need human input or external action to proceed.
    The system will move the task to blocked/ until the human responds.

If neither control tool is called, the task remains in progress for the next
cycle. Be concise in your final reply — it is appended to the human-readable
conversation thread.
"""


class ContextBuilder:
    """Build the LLM messages list from rules + task per the Completion Promise Pattern.

    Each cycle reconstructs context from scratch: the system prompt is `rules.md`
    content plus generic agent instructions; the user message is the entire task
    state (metadata, description, subtasks, conversation history, optional
    task-level instructions).

    No prior LLM conversation is preserved across cycles.
    """

    def build(
        self, rules: str, task: Task, vault_name: str = "cc-assistant"
    ) -> list[Message]:
        system_text = self._build_system(rules, vault_name)
        user_text = self._build_user(task)
        return [
            Message(role="system", content=system_text),
            Message(role="user", content=user_text),
        ]

    @staticmethod
    def _build_system(rules: str, vault_name: str = "cc-assistant") -> str:
        prefix = f"_(Obsidian vault name: `{vault_name}`)_\n\n"
        if rules.strip():
            return prefix + f"{rules.rstrip()}\n\n{_SYSTEM_AGENT_INSTRUCTIONS}"
        return prefix + _SYSTEM_AGENT_INSTRUCTIONS

    @staticmethod
    def _build_user(task: Task) -> str:
        lines: list[str] = []
        lines.append(f"# Task {task.id}: {task.title}")
        lines.append("")

        # Metadata block
        meta_lines = [f"- **Project:** {task.project or '(none)'}"]
        if task.parent:
            meta_lines.append(f"- **Parent:** {task.parent}")
        meta_lines.append(f"- **Priority:** {task.priority.value}")
        if task.tags:
            meta_lines.append(f"- **Tags:** {', '.join(task.tags)}")
        meta_lines.append(f"- **auto_approve:** {task.auto_approve}")
        lines.extend(meta_lines)
        lines.append("")

        # Task-level instructions (overrides rules.md for this task only)
        if task.instructions.strip():
            lines.append("## Task Instructions")
            lines.append(task.instructions.rstrip())
            lines.append("")

        # Description
        lines.append("## Description")
        lines.append(task.description.rstrip() if task.description else "(empty)")
        lines.append("")

        # Motivation (why)
        if task.why and task.why.strip():
            lines.append("## Motivation (why)")
            lines.append(task.why.rstrip())
            lines.append("")

        # Success Criteria (measure)
        if task.measure and task.measure.strip():
            lines.append("## Success Criteria (measure)")
            lines.append(task.measure.rstrip())
            lines.append("Self-check against each item before calling mark_complete.")
            lines.append("")

        # Source Files
        if task.source_files:
            lines.append("## Source Files")
            lines.append("These files are pre-read context for this task:")
            for sf in task.source_files:
                lines.append(f"- `{sf}`")
            lines.append("")

        # Subtasks
        if task.subtasks:
            lines.append("## Subtasks")
            for sub in task.subtasks:
                tail = (
                    f" — blocked on: {sub.blocking_reason}"
                    if sub.blocking_reason
                    else ""
                )
                lines.append(f"- [{sub.status.value}] {sub.id}: {sub.title}{tail}")
            lines.append("")

        # Conversation history
        if task.conversation:
            lines.append("## Conversation")
            for entry in task.conversation:
                ts = entry.timestamp.strftime("%Y-%m-%d %H:%M")
                lines.append(f"### [{entry.role.value}] {ts}")
                lines.append(entry.content.rstrip())
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"
