from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.models import ConversationEntry, Priority, Task, Who


def _quote_yaml_string(s: str) -> str:
    """Quote a string for safe YAML emission, escaping backslashes and double quotes."""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def write_task_file(task: Task, path: Path) -> None:
    """Write a Task model to a Markdown file."""
    lines: list[str] = []

    lines.append("---")
    lines.append(f'id: "{task.id}"')
    lines.append(f"title: {_quote_yaml_string(task.title)}")
    if task.project:
        lines.append(f"project: {_quote_yaml_string(task.project)}")
    if task.parent is not None:
        lines.append(f"parent: {_quote_yaml_string(task.parent)}")
    if task.priority != Priority.P1:
        lines.append(f"priority: {task.priority.value}")
    if task.tags:
        lines.append(f"tags: [{', '.join(task.tags)}]")

    if task.who != Who.CLAUDE:
        lines.append(f"who: {task.who.value}")
    if task.when is not None:
        lines.append(f"when: {_quote_yaml_string(task.when)}")
    if task.type is not None:
        lines.append(f"type: {task.type.value}")
    if task.intent is not None:
        lines.append(f"intent: {task.intent.value}")

    lines.append(f"created: {_format_dt(task.created)}")
    lines.append(f"updated: {_format_dt(task.updated)}")
    if not task.auto_approve:
        lines.append("auto_approve: false")
    if task.depends_on:
        lines.append(f"depends_on: [{', '.join(task.depends_on)}]")

    if task.measure:
        if "\n" in task.measure:
            lines.append("measure: |")
            for line in task.measure.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"measure: {_quote_yaml_string(task.measure)}")
    if task.why:
        if "\n" in task.why:
            lines.append("why: |")
            for line in task.why.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"why: {_quote_yaml_string(task.why)}")
    if task.source_files:
        lines.append("source_files:")
        for sf in task.source_files:
            lines.append(f"  - {_quote_yaml_string(sf)}")
    if task.status_reason is not None:
        lines.append(f"status_reason: {_quote_yaml_string(task.status_reason)}")

    if task.instructions:
        if "\n" in task.instructions:
            lines.append("instructions: |")
            for line in task.instructions.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(f"instructions: {_quote_yaml_string(task.instructions)}")

    if task.subtasks:
        lines.append("subtasks:")
        for sub in task.subtasks:
            lines.append(f'  - id: "{sub.id}"')
            lines.append(f"    title: {_quote_yaml_string(sub.title)}")
            lines.append(f"    status: {sub.status.value}")
            if sub.blocking_reason:
                lines.append(f"    blocking_reason: {_quote_yaml_string(sub.blocking_reason)}")

    lines.append("---")
    lines.append("")

    lines.append("## 任务描述")
    lines.append(task.description)
    lines.append("")

    lines.append("## 对话")
    lines.append("")
    for entry in task.conversation:
        lines.append(_format_conversation_entry(entry))

    path.write_text("\n".join(lines), encoding="utf-8")


def append_conversation(path: Path, entry: ConversationEntry) -> None:
    """Append a conversation entry to an existing task file."""
    text = path.read_text(encoding="utf-8")
    formatted = _format_conversation_entry(entry)
    text = text.rstrip() + "\n" + formatted
    path.write_text(text, encoding="utf-8")


def _format_conversation_entry(entry: ConversationEntry) -> str:
    """Format a single conversation entry as Markdown."""
    header = f"### [{entry.role.value}] {_format_dt(entry.timestamp)}"
    return f"{header}\n{entry.content}\n"


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def append_system_entry(path: Path, message: str) -> None:
    """Append a `### [系统] <ts>` conversation entry to a task file.

    Used by the orchestrator to surface non-LLM failures (e.g.
    provider_unavailable) directly in Obsidian. The user sees the
    message inline in the task; the next mtime tick is short-circuited
    by `is_pending_placeholder_turn` once `append_placeholder` follows.

    Caller should follow with `append_placeholder(path)` so the user has
    a [我] turn ready to respond into. This function does not scaffold
    that on its own — there are flows (e.g. status changes mid-error)
    where the placeholder is conditional, so we keep it explicit.
    """
    from src.models import ConversationEntry, ConversationRole as _CR
    entry = ConversationEntry(
        role=_CR.SYSTEM,
        timestamp=datetime.now(),
        content=message.rstrip(),
    )
    append_conversation(path, entry)


def append_unparseable_file_marker(path: Path, message: str) -> None:
    """Append a free-form text block at the end of a malformed task file.

    `task_malformed` means the parser couldn't even read the frontmatter,
    so the file's structure isn't trustworthy. We can't safely append a
    `### [系统]` conversation entry — we don't know if `## 对话` is in
    place, where the body ends, etc. Just append a clearly-delimited
    text block at the file end so the user opens the file in Obsidian
    and sees what's wrong.

    Idempotent-ish: the block is identified by a unique ASCII marker
    line (`<!-- cc-assistant: file-malformed-notice -->`). If that line
    is already in the file, this is a no-op — we don't keep stacking
    notices on every save.
    """
    text = path.read_text(encoding="utf-8")
    marker = "<!-- cc-assistant: file-malformed-notice -->"
    if marker in text:
        return
    ts = _format_dt(datetime.now())
    block = (
        f"\n\n{marker}\n"
        f"> **[系统] {ts}** — cc-assistant 没能读懂这个任务文件。\n"
        f"> {message}\n"
        f"> 修好上面的 frontmatter 再保存,这条提示会留在文件里直到你删掉它。\n"
    )
    path.write_text(text.rstrip() + block, encoding="utf-8")


def append_placeholder(path: Path) -> None:
    """Append a pending [我] placeholder turn at the end of the task file.

    Idempotent: if the file already ends with a pending placeholder
    turn (per parser's is_pending_placeholder_turn), this is a no-op.
    Otherwise appends:

        ### [我] <now>
        *(在这里写下一条，保存即触发)*

    The header timestamp is set to datetime.now(); it's a visual marker
    only and not consumed by any logic.
    """
    from src.board.parser import PLACEHOLDER_TEXT, is_pending_placeholder_turn, parse_task_file

    try:
        task = parse_task_file(path)
    except Exception:  # pylint: disable=broad-except
        # Malformed file — treat as needing a placeholder; the user can
        # still benefit from the scaffold even if frontmatter has issues.
        task = None

    if task is not None and is_pending_placeholder_turn(task):
        return

    text = path.read_text(encoding="utf-8")
    header = f"### [我] {_format_dt(datetime.now())}"
    block = f"{header}\n{PLACEHOLDER_TEXT}\n"
    new_text = text.rstrip() + "\n\n" + block
    path.write_text(new_text, encoding="utf-8")
