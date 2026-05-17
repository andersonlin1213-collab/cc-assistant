from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

import frontmatter

from src.models import (
    ConversationEntry,
    ConversationRole,
    Priority,
    Subtask,
    SubtaskStatus,
    Task,
    TaskIntent,
    TaskType,
    Who,
)

# Matches conversation entry headers, tolerating two real-world variants
# observed during 5/3 dogfood that used to silently drop the entry
# (parser kept it as body text under the previous header, and downstream
# is_pending_placeholder_turn answered the wrong question for hours):
#
#   ### [我] 2026-05-02 07:35                  ← canonical (HH:MM)
#   ### [Human] 2026-04-26 14:00               ← legacy [Human] tag
#   ### [我] 2026-05-03                        ← time-of-day omitted
#   ### [AI] 2026-05-02 10:50 — 整合稿         ← canonical + suffix
#   ### [AI] 2026-05-03 — 跳过本轮             ← date-only + suffix
#
# Time-of-day is optional; `_parse_datetime` falls back to 00:00:00 when
# only a date is captured. Anything after a single space following the
# timestamp is treated as a free-form suffix and discarded.
_CONVERSATION_HEADER = re.compile(
    r"^###\s+\[(?P<role>Human|我|AI|系统)\]\s+"
    r"(?P<ts>\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)"
    r"(?:\s+.*)?\s*$"
)

# Lenient header — matches any `### [Human|我|AI] <anything>`. Used as a
# forgive-then-warn fallback when the strict canonical form above misses,
# so a new mobile-Obsidian variant lands in `parse_warnings` instead of
# getting silently dropped (the 5/3 dogfood failure mode). Captures role
# and the rest of the line so we can scavenge a date token.
_LENIENT_CONVERSATION_HEADER = re.compile(
    r"^###\s+\[(?P<role>Human|我|AI|系统)\]\s*(?P<rest>.*?)\s*$"
)
# Date token — first date-shape we find in the lenient `rest` becomes the
# entry timestamp. Liberal on punctuation widths since the timestamp is
# only a display marker and not consumed downstream.
_DATE_TOKEN = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}(?:[\sT]\d{1,2}:\d{2}(?::\d{2})?)?"
)


class TaskFileMalformed(ValueError):
    """Raised when a Markdown file in tasks/ lacks the frontmatter required to
    be a Task. Common cause: a draft file created on mobile in Obsidian without
    filling in the template. The caller should log + skip rather than crash."""


_REQUIRED_FRONTMATTER_FIELDS = ("title",)


_ENRICH_LOCK = threading.Lock()


def enrich_minimal_task(path: Path, tasks_dir: Path) -> bool:
    """Auto-fill task frontmatter for minimal files.

    Idempotent. Two enrichment paths:

    1. Title-only files (any column): if title is set but id/created/updated
       are missing, fill those.
    2. Bare files in todo/ or backlog/: title is missing too, but the
       file's location signals user intent. Synthesize title = path.stem,
       then fill the rest.

    The id is the next available numeric slot across the entire vault
    (max numeric id of all parseable tasks + 1), zero-padded to three
    digits as a quoted string ("007"). Non-numeric ids in the corpus
    (e.g. "demo-001") are ignored when computing max.

    Concurrency: uses a module-level threading.Lock so two simultaneous
    enrichments allocate distinct sequential ids.

    Returns True iff the file was written.
    """
    with _ENRICH_LOCK:
        text = path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        meta = dict(post.metadata or {})
        original_meta = dict(post.metadata or {})

        title = meta.get("title")
        if not title:
            # Recovery: in todo/ or backlog/, file location IS the task signal.
            # Synthesize title from filename stem.
            if _path_implies_task(path) and path.stem and not path.name.startswith("."):
                meta["title"] = path.stem
            else:
                return False  # bare file outside task-implied folder — skip

        # At this point title is guaranteed to be set (either was set in
        # frontmatter, or synthesized just now).
        if not meta.get("id"):
            meta["id"] = _allocate_next_id(tasks_dir)
        if not meta.get("created"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            meta["created"] = mtime.strftime("%Y-%m-%d %H:%M")
        if not meta.get("updated"):
            meta["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Idempotency: only write back if something actually changed.
        if meta == original_meta:
            return False

        post.metadata = meta
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return True


def _path_implies_task(path: Path) -> bool:
    """True if the file's direct parent is a column where bare files imply
    user intent (`todo/` or `backlog/` — the natural creation points).

    Direct children only — `tasks/todo/sub/foo.md` does not qualify because
    `path.parent.name` is "sub", not "todo". This matches the watcher's
    column whitelist scope.
    """
    return path.parent.name in ("todo", "backlog")


def _allocate_next_id(tasks_dir: Path) -> str:
    """Return next sequential numeric id as zero-padded 3-digit string."""
    existing = _scan_existing_numeric_ids(tasks_dir)
    next_n = (max(existing) + 1) if existing else 1
    return f"{next_n:03d}"


def _scan_existing_numeric_ids(tasks_dir: Path) -> set[int]:
    """Collect all numeric `id` values in vault task files."""
    ids: set[int] = set()
    columns = ("backlog", "todo", "doing", "blocked", "review")
    for col in columns:
        col_dir = tasks_dir / col
        if col_dir.exists():
            for f in col_dir.glob("*.md"):
                ids |= _numeric_ids_in_file(f)
    done_dir = tasks_dir / "done"
    if done_dir.exists():
        for f in done_dir.glob("*/*.md"):
            ids |= _numeric_ids_in_file(f)
    return ids


def _numeric_ids_in_file(path: Path) -> set[int]:
    try:
        text = path.read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        raw = post.metadata.get("id") if post.metadata else None
    except (OSError, ValueError):
        return set()
    if raw in (None, ""):
        return set()
    s = str(raw)
    if s.isdigit():
        return {int(s)}
    return set()


def parse_task_string(text: str, source_path: str | None = None) -> Task:
    """Parse a Markdown task string into a Task model.

    Raises TaskFileMalformed only when the frontmatter is missing or has no
    `title`, or when an explicit `created`/`updated` value fails to parse.
    Missing `id`/`created`/`updated` are now allowed and trigger synthesized
    defaults (empty id, epoch datetime); the enrichment helper writes them
    back when called.
    """
    post = frontmatter.loads(text)
    meta = post.metadata
    body = post.content

    where = f" in {source_path}" if source_path else ""
    if not meta:
        raise TaskFileMalformed(f"no frontmatter found{where}")
    for field in _REQUIRED_FRONTMATTER_FIELDS:
        if field not in meta or meta[field] in (None, ""):
            raise TaskFileMalformed(
                f"missing required frontmatter field {field!r}{where}"
            )

    # `created` and `updated` may be absent on minimal task files that haven't
    # been enriched yet. Use the epoch as a sentinel — visible to readers as
    # 1970-01-01 — and let the enrichment path overwrite it on first daemon
    # touch. Any explicit value, well-formed or not, is parsed normally.
    try:
        created = _parse_datetime(meta["created"]) if meta.get("created") else datetime.fromtimestamp(0)
        updated = _parse_datetime(meta["updated"]) if meta.get("updated") else datetime.fromtimestamp(0)
    except ValueError as e:
        raise TaskFileMalformed(f"unparseable datetime{where}: {e}") from e

    subtasks = [
        Subtask(
            id=str(s["id"]),
            title=s["title"],
            status=SubtaskStatus(s.get("status", "todo")),
            blocking_reason=s.get("blocking_reason"),
        )
        for s in meta.get("subtasks", []) or []
    ]

    warnings: list[str] = []
    description, conversation = _parse_body(body, warnings)

    parent_value = meta.get("parent")
    parent = str(parent_value) if parent_value not in (None, "", "null") else None

    provider_value = meta.get("provider")
    provider = (
        str(provider_value).strip()
        if provider_value not in (None, "", "null")
        else None
    )

    # Parse the 8 new fields with sensible defaults
    who_value = meta.get("who", "claude") or "claude"
    type_value = meta.get("type")
    intent_value = meta.get("intent")
    source_files = meta.get("source_files", []) or []
    when_value = meta.get("when")
    if when_value == "":
        when_value = None
    status_reason_value = meta.get("status_reason")
    if status_reason_value == "":
        status_reason_value = None

    # Convert frontmatter enum-typed fields. Bare `ValueError` from a
    # `Who('ai')` etc. would propagate out of `parse_task_string`,
    # bypass `run_cycle`'s `except TaskFileMalformed` catch, and only
    # land in `watcher_callback_failed` logs — invisible to the user in
    # Obsidian. Re-wrap as `TaskFileMalformed` so the orchestrator's
    # `[系统]` marker pathway surfaces the bad value in the task file
    # itself. (This is the same silent-fail family the parser closed
    # earlier for conversation headers — same playbook.)
    try:
        priority = Priority(meta.get("priority") or "P1")
        who = Who(str(who_value))
        type_ = (
            TaskType(str(type_value))
            if type_value not in (None, "", "null")
            else None
        )
        intent = (
            TaskIntent(str(intent_value))
            if intent_value not in (None, "", "null")
            else None
        )
    except ValueError as e:
        raise TaskFileMalformed(
            f"frontmatter enum value{where}: {e}"
        ) from e

    return Task(
        id=str(meta["id"]) if meta.get("id") else "",
        title=meta["title"],
        project=meta.get("project", "") or "",
        parent=parent,
        priority=priority,
        tags=meta.get("tags", []) or [],
        created=created,
        updated=updated,
        auto_approve=meta.get("auto_approve", True),
        depends_on=meta.get("depends_on", []) or [],
        instructions=meta.get("instructions", "") or "",
        who=who,
        when=when_value if when_value is None else str(when_value),
        type=type_,
        intent=intent,
        measure=str(meta.get("measure", "") or ""),
        why=str(meta.get("why", "") or ""),
        source_files=[str(p) for p in source_files],
        status_reason=status_reason_value if status_reason_value is None else str(status_reason_value),
        subtasks=subtasks,
        description=description,
        conversation=conversation,
        source_path=source_path,
        parse_warnings=warnings,
        provider=provider,
    )


def parse_task_file(path: Path) -> Task:
    """Parse a Markdown task file into a Task model."""
    text = path.read_text(encoding="utf-8")
    return parse_task_string(text, source_path=str(path))


def _parse_body(
    body: str, warnings: list[str]
) -> tuple[str, list[ConversationEntry]]:
    """Split the markdown body into description and conversation entries.

    `warnings` is appended to in-place: each entry describes a forgive-then-warn
    fallback (missing `## 对话` divider, lenient header match, fully unparseable
    chunk). The orchestrator surfaces these via `parser_warning` log entries.
    """
    parts = re.split(r"^## 对话\s*$", body, maxsplit=1, flags=re.MULTILINE)

    desc_part = parts[0]
    if len(parts) >= 2:
        conv_text = parts[1]
    else:
        # Fallback when `## 对话` is missing: a file created via mobile
        # Obsidian (or any path that bypassed write_task_file) carries
        # `### [AI]/[我]` entries directly under `## 任务描述`. Without
        # this fallback parser returns an empty conversation list, which
        # causes is_pending_placeholder_turn to always return False, which
        # makes the orchestrator cycle the task forever. Use the first
        # `### [Human|我|AI] <ts>` header as the boundary.
        first_header = re.search(
            r"^### \[(?:Human|我|AI|系统)\] \d{4}",
            desc_part,
            flags=re.MULTILINE,
        )
        if first_header:
            conv_text = desc_part[first_header.start():]
            desc_part = desc_part[:first_header.start()]
            warnings.append(
                "对话_header_missing: used first '### [role] <date>' as boundary"
            )
        else:
            conv_text = ""

    desc_match = re.split(r"^## 任务描述\s*$", desc_part, maxsplit=1, flags=re.MULTILINE)
    description = desc_match[1].strip() if len(desc_match) > 1 else desc_part.strip()

    conversation: list[ConversationEntry] = []
    if not conv_text.strip():
        return description, conversation
    entries = re.split(r"(?=^### \[)", conv_text, flags=re.MULTILINE)
    # Truncate trailing H2 (e.g., `## 执行日志`) from the LAST entry chunk
    # only. H2 sub-headings INSIDE earlier entries' content (typical AI
    # markdown output) are preserved — cutting on those was a real bug:
    # 003-零售顾问专家.md 2026-05-02 lost 4 subsequent [我] turns because
    # an [AI] reply contained `## 🔒 安全先看`, and replay then looped
    # backfills indefinitely thinking last entry was that [AI].
    if entries:
        entries[-1] = re.split(
            r"^## ", entries[-1], maxsplit=1, flags=re.MULTILINE
        )[0]

    for entry_text in entries:
        entry_text = entry_text.strip()
        if not entry_text:
            continue

        first_line = entry_text.split("\n", 1)[0]
        entry = _parse_entry(first_line, entry_text, warnings)
        if entry is not None:
            conversation.append(entry)

    return description, conversation


def _parse_entry(
    first_line: str, entry_text: str, warnings: list[str]
) -> ConversationEntry | None:
    """Parse a single conversation entry chunk, forgive-then-warn style.

    Tries the canonical header regex first (no warning). If that misses but
    the chunk still looks like `### [role] ...`, scavenge a date token from
    the rest of the line and emit a warning so the variant becomes visible
    in logs. If even the lenient form misses, drop the chunk + warn — never
    silently lose, which was the 5/3 dogfood failure mode.
    """
    canonical = _CONVERSATION_HEADER.match(first_line)
    content = "\n".join(entry_text.split("\n")[1:]).strip()

    if canonical:
        return ConversationEntry(
            role=ConversationRole(canonical.group("role")),
            timestamp=_parse_datetime(canonical.group("ts")),
            content=content,
        )

    lenient = _LENIENT_CONVERSATION_HEADER.match(first_line)
    if lenient:
        rest = lenient.group("rest")
        date_match = _DATE_TOKEN.search(rest)
        if date_match:
            try:
                ts = _parse_datetime(date_match.group(0))
            except ValueError:
                ts = datetime.now()
                warnings.append(
                    f"conversation_header_unparseable_date: {first_line[:80]!r} "
                    "(used now())"
                )
            else:
                warnings.append(
                    f"conversation_header_lenient: {first_line[:80]!r}"
                )
        else:
            ts = datetime.now()
            warnings.append(
                f"conversation_header_no_timestamp: {first_line[:80]!r} "
                "(used now())"
            )
        return ConversationEntry(
            role=ConversationRole(lenient.group("role")),
            timestamp=ts,
            content=content,
        )

    warnings.append(f"conversation_header_dropped: {first_line[:80]!r}")
    return None


def _parse_datetime(value: str | datetime) -> datetime:
    """Parse a datetime string or return as-is if already datetime."""
    if isinstance(value, datetime):
        return value
    value = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",  # date-only — used when conversation header omits HH:MM
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {value}")


PLACEHOLDER_TEXT = "*(在这里写下一条，保存即触发)*"


def is_pending_placeholder_turn(task: "Task") -> bool:
    """True iff the last conversation entry is a pending [我] placeholder.

    Pending = the user has NOT typed a real reply. Specifically:
      - last entry's role is HUMAN, AND
      - last entry's content stripped of whitespace is empty OR equals
        the PLACEHOLDER_TEXT sentinel.

    Orchestrator uses this to skip cycles when a save event arrived but
    the conversation hasn't actually advanced.
    """
    from src.models import ConversationRole  # local import avoids circular
    if not task.conversation:
        return False
    last = task.conversation[-1]
    if last.role is not ConversationRole.HUMAN:
        return False
    stripped = last.content.strip()
    return stripped == "" or stripped == PLACEHOLDER_TEXT
