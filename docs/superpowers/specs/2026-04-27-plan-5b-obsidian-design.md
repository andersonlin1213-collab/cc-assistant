# Plan 5b — Obsidian-as-UI Design Spec

## Overview

Replace the FastAPI mobile Web UI proposed in the original `2026-04-26-local-ai-task-agent-design.md` (Layer 4 / Mobile Web UI section) with an Obsidian vault. The cc-assistant `tasks/` directory becomes the vault root; users browse and edit tasks via the Obsidian app on desktop and mobile; Obsidian Sync (paid, official) handles cross-device replication; the local cc-assistant daemon continues to watch task files unchanged.

**Net effect on the architecture:** delete one custom service (FastAPI), one custom merger (timestamp-based conversation merge), and one transport (git auto-commit/pull on the task tree). Replace with one off-the-shelf product (Obsidian) and a sync subscription.

**Rationale:**
- The user already uses Obsidian for personal notes and Claude Code conversation history. Mobile editing, folder hierarchy, and YAML frontmatter rendering work day one.
- Original Plan 5b (FastAPI) estimated ~10 days; this design estimates ~4 days. The work avoided is auth, deployment to a remote server, custom Jinja templates, and a custom merge resolver.
- Obsidian Sync handles bidirectional file conflicts natively. The daemon does not need to participate in conflict resolution.

## Decisions Locked During Brainstorming

| Question | Choice |
|---|---|
| Replace or supplement the original Web UI? | **Replace** — Obsidian is the only mobile front end |
| Sync transport | **Obsidian Sync** (official paid service) |
| Vault layout | **Dedicated cc-assistant vault** (separate from user's personal vault) |
| Vault root | `tasks/` directory inside the existing repo |
| Task model fields to add | **All seven** proposed: `who`, `when`, `type`, `measure`, `why`, `source_files`, `status_reason` (+ an eighth, `intent`, derived during design) |
| Kanban view mechanism | **Bases** (Obsidian native, 1.7+) |

## Architecture

```
+--------------- Local Windows (cc-assistant repo) -----------------+
|                                                                   |
|  <your-user>/projects/cc-assitant/                       |
|  +- src/                  <- code (git, untouched)                |
|  +- tests/                                                        |
|  +- docs/                                                         |
|  +- tasks/                <- Obsidian Vault root                  |
|     +- .obsidian/         <- Obsidian config + Bases + theme      |
|     +- views.base         <- Bases view definitions               |
|     +- backlog/ todo/ doing/ blocked/ review/ done/               |
|     +- templates/                                                 |
|     +- _attachments/      <- new; image attachments               |
|                                                                   |
|  cc-assistant daemon (from Plan 5a, unchanged in core loop)       |
|   +- watchdog monitors tasks/{6 columns}/*.md                     |
|       +- ignores .obsidian/, _attachments/, templates/, .trash/   |
|                                                                   |
|  Obsidian desktop app (must run for Sync to land bytes on disk)   |
+-------------------------------------------------------------------+
                          ^
                          | Obsidian Sync (1-3s round trip)
                          v
+--------------- Mobile Obsidian app -------------------------------+
|  Open cc-assistant vault -> default to views.base                 |
|  Card tap -> task detail; Properties UI for frontmatter           |
|  Append conversation -> Save -> Sync -> daemon picks up           |
+-------------------------------------------------------------------+
```

**What is removed compared to `2026-04-26-local-ai-task-agent-design.md`:**

| Removed | Reason |
|---|---|
| `src/dispatcher/sync.py` (git auto-commit/push/pull) | Obsidian Sync replaces the transport |
| Custom conversation-timestamp merger | Obsidian Sync's conflict files replace it |
| FastAPI app on remote server (never implemented) | Obsidian app replaces the front end |
| Mobile Web UI templates (`web/templates/*.html`) | Same |
| End-to-end latency budget of ~5 minutes (git pull cycle) | Now ~1-3 seconds (Obsidian Sync push) |

**What is preserved:** every layer Plans 1-4 and 5a delivered — board parser/writer, dispatcher (watchdog + scheduler), orchestrator, tools, rules, structured logging, CLI lifecycle. The new design treats Obsidian as another file-modifying client; the daemon does not know it exists.

## Vault Layout

### Directory Structure

```
tasks/                                  <- vault root
+- .obsidian/                           <- created by Obsidian on first open
|  +- app.json                          <- in git (cross-device config)
|  +- workspace.json                    <- gitignore (per-device state)
|  +- workspace-mobile.json             <- gitignore
|  +- core-plugins.json
|  +- themes/                           <- e.g. Minimal
|  +- plugins/                          <- only if community plugins are used
+- .gitignore                           <- new
+- views.base                           <- Bases view definitions
+- README.md                            <- welcome page for the vault
+- backlog/  todo/  doing/  blocked/  review/  done/
+- templates/
|  +- default.md
+- _attachments/                        <- Obsidian default attachment folder
```

### `tasks/.gitignore` (new)

```
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache
.trash/
```

`app.json`, `views.base`, themes, and plugin configs are committed so the configuration reproduces across machines.

### Repository root `.gitignore` additions

```
tasks/_attachments/        # binary attachments handled by Obsidian Sync
```

### Watcher Ignore Patterns

`src/dispatcher/watcher.py` already ignores `templates/`. Add:

```python
IGNORE_PATTERNS = [
    "**/.obsidian/**",
    "**/_attachments/**",
    "**/.trash/**",
    "**/templates/**",
    "**/*(conflict*).md",   # Obsidian Sync conflict files
]
```

Without these, theme switches and plugin reconfiguration would trigger spurious LLM cycles.

### Daemon Startup Health Check (new)

On `cc-assistant run` startup, log a warning (not fatal) if `tasks/.obsidian/` does not exist:

> "Vault not initialized. Open `tasks/` in Obsidian once to create the vault, then restart."

This does not block startup so dry-runs and tests can proceed without a vault.

## Task Model Extension

### Frontmatter Schema

```yaml
---
id: "025"
title: 个人 portfolio 网站
project: portfolio-website
parent: null
priority: P1
tags: [frontend, design]

# === New in Plan 5b ===
who: human                       # claude / human / both
when: 本周日（2026-05-03）前      # natural-language deadline (display only)
type: complex                    # simple / complex; AI fills after decomposition
intent: null                     # null / resume / approve / reject / pause

created: 2026-04-26 14:00
updated: 2026-04-26 15:31
auto_approve: true
depends_on: []

measure: |                       # success criteria; AI self-checks against
  1) 三端布局一致
  2) Lighthouse 移动端 >= 90
  3) 部署到 vercel 公开访问
why: |                           # motivation; flows into LLM system prompt
  秋招需要个 portfolio
source_files:                    # AI pre-reads these for context
  - src/portfolio/old-design.tsx
  - docs/branding.md
status_reason: null              # only set when in blocked/

instructions: |
  请优先使用 Tailwind CSS。
subtasks:
  - id: "025-1"
    title: 设计语言风格选型
    status: blocked
    blocking_reason: 需要从 A/B/C 选择
---
```

### Pydantic Model Changes (`src/models.py`)

```python
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

class Task(BaseModel):
    # existing fields...
    who: Who = Who.CLAUDE
    when: Optional[str] = None
    type: Optional[TaskType] = None
    intent: Optional[TaskIntent] = None
    measure: str = ""
    why: str = ""
    source_files: list[str] = Field(default_factory=list)
    status_reason: Optional[str] = None
```

### Frontmatter Field Order

Fixed order in writes (parser is order-insensitive on read):

```
id, title, project, parent, priority, tags,
who, when, type, intent,
created, updated, auto_approve, depends_on,
measure, why, source_files, status_reason,
instructions, subtasks
```

The Properties UI in Obsidian renders in declaration order. Putting `who / when / type / intent` directly after `priority` makes the most decision-relevant fields visible above the fold on a phone screen.

### Parser & Writer Changes

- `src/board/parser.py::parse_task_string` reads the eight new keys; missing keys fall back to defaults.
- `src/board/writer.py::write_task` writes them. `measure`, `why`, and `instructions` use YAML block scalar (`|`) to preserve line breaks.

### Template Update (`tasks/templates/default.md`)

```yaml
---
id: ""
title: ""
project: ""
parent: null
priority: P1
tags: []
who: human                  # default to human; force the user to think
when: ""
type: null                  # AI will fill
intent: null
created: ""
updated: ""
auto_approve: true
depends_on: []
measure: ""                 # required: success criteria
why: ""                     # required: motivation
source_files: []
status_reason: null
instructions: ""
subtasks: []
---
## 任务描述

## 对话
```

### LLM Context Changes (`src/agent/context.py`)

`build_llm_context` adds these fields to the system message's "task overview" block:
- `measure` becomes a self-check checklist the model is told to verify before marking done.
- `why` enters the "task motivation" segment, influencing prioritization decisions.
- `source_files` triggers `file_ops.read` calls before LLM invocation; contents are injected as context.

### Daemon Filter on `who`

Watcher detects a file change. Before dispatching to orchestrator, check `who`:
- `who == claude` -> dispatch normally.
- `who in [human, both]` -> log "skipped: not assigned to AI" and do not invoke the LLM.

This is the on-disk equivalent of the rules-side routing table. It is enforced before LLM cost is incurred.

### Daemon Handling of `intent`

When watcher detects a frontmatter change where `intent` transitioned from `null` to non-null, the orchestrator handles it as a **mechanical action** (no LLM call):

| `intent` | Action |
|---|---|
| `resume` | Move file from `blocked/` to `doing/`, clear `intent`, log |
| `approve` | Move file from `review/` to `done/YYYY-MM/`, clear `intent`, log |
| `reject` | Move file from `review/` to `todo/`, clear `intent`, log; conversation is preserved so user can append a `### [Human]` note |
| `pause` | Move file from `doing/` to `backlog/`, clear `intent`, log |

After the move, the watcher fires again on the new location. If `who == claude` and the new column dispatches (`todo/` or `doing/`), the next normal LLM cycle runs.

The intent mechanism replaces drag-and-drop in a kanban: mobile UX is a single property edit instead of a folder move.

### No Migration

`tasks/{backlog,todo,doing,blocked,review,done}/` are empty at HEAD `405c5e5`. New schema applies to all future tasks. Test fixtures under `tests/fixtures/` are updated alongside the model.

## Bases Views

`tasks/views.base` ships with four views. The vault's default-open file is set to `views.base` in `.obsidian/app.json` so opening the vault on phone immediately shows views.

### View 1: Six-Column Kanban (default tab)

```
[BACKLOG]   [TODO]      [DOING]     [BLOCKED]   [REVIEW]    [DONE]
+-card-+    +-card-+    +-card-+    +-card-+    +-card-+    +-card-+
```

- Group by `file.folder`.
- Columns ordered: `backlog, todo, doing, blocked, review, done`.
- Card displays: `title`, `priority` badge, `who` badge, `when` if set, first 3 tags.
- Sort within column: `priority asc`, then `created desc`.

### View 2: "Who Needs Me" (recommended phone home tab)

Single-column list of tasks where `status_reason` is set OR `who in [human, both]`. Sorted by `priority`. This is the "what should I do right now" view.

### View 3: By Project

Grouped list by `project`, filtered to non-`done`. Used for weekly review across project lines.

### View 4: This Week

Filter by `when` containing one of `今天 / 明天 / 本周 / 本周日`. String containment, no date parsing. Skeleton sketch only — exact filter syntax depends on Bases version.

### `views.base` Sketch

```yaml
filters:
  not:
    file.folder.contains: ["templates", "_attachments"]

formulas:
  status: file.folder

views:
  - type: board
    name: 看板
    group_by: status
    columns: [backlog, todo, doing, blocked, review, done]
    sort: [priority, "-created"]
    card:
      title: title
      badges: [priority, who]
      footer: when

  - type: list
    name: 谁等我
    filter:
      or:
        - status_reason.is_not_empty
        - who: [human, both]
    sort: [priority]

  - type: list
    name: 按 project
    group_by: project
    filter:
      not:
        status: done

  - type: list
    name: 本周
    filter:
      when.contains_any: ["今天", "明天", "本周", "本周日"]
```

This is design intent, not a final configuration. Bases syntax is still evolving in Obsidian 1.7-1.9; implementation aligns to current docs at https://help.obsidian.md/bases.

### Performance Note

Bases performance on mobile degrades past ~500 tasks per vault. MVP usage is well under that; no optimization is required for v1.

## Sync & Conflict Handling

### Sync Path

```
Mobile Obsidian -> Obsidian Sync server -> Desktop Obsidian (must be running)
                                                     |
                                                     v
                                          tasks/blocked/036-xxx.md
                                                     |
                                                     v
                                  watchdog -> debounce 2s -> orchestrator
```

**Critical pre-condition:** the desktop Obsidian app must be running for Sync to write to local disk. Without it, Sync queues changes in the cloud but never reaches the daemon's watcher.

### Daemon Startup Adds an Obsidian Process Check

`cc-assistant run` checks for a running `Obsidian.exe` process at startup. If absent, log a warning (not fatal) suggesting the user start Obsidian. Implementation uses `psutil.process_iter`. Skipping this in `--dry-run` mode.

### Git's New Role

| Path | Old plan | New plan |
|---|---|---|
| `src/`, `tests/`, `docs/` | git | git (unchanged) |
| `tasks/*.md` | git auto-commit + push every write | **No auto-commit.** User manually commits as backup checkpoints. |
| `tasks/.obsidian/app.json`, `views.base` | n/a | git (so config reproduces) |
| `tasks/_attachments/` | n/a | gitignore (Obsidian Sync handles binaries) |

`src/dispatcher/sync.py` and `tests/test_sync.py` are removed during Plan 5b execution.

### Conflict Resolution

Obsidian Sync resolves bidirectional conflicts at the file level. When the same file is modified concurrently on two devices, the second write to land becomes `036-xxx (conflict 2026-04-27 15:32:01).md` alongside the original.

The daemon ignores conflict files via the `**/*(conflict*).md` watcher pattern. Resolution is the user's responsibility, performed in Obsidian on either end. There is no automated merger; the original Plan 5b's timestamp-based conversation merger is **not** implemented.

### Edge Case: Daemon Writes While User Saves on Phone

- Daemon writes use atomic rename (`tmp.xxx -> 036-xxx.md`); already implemented in Plan 1.
- Obsidian's local file watcher recognizes atomic rename and uploads the post-rename file.
- True concurrent write race is expected to be < 1% in practice. If observed in real use, mitigation is to add an mtime check before the daemon writes (delay if file changed within last 5 seconds). Not implemented in v1.

## Mobile Interaction Flow

### Notification Path

When the orchestrator moves a task to `blocked/`, it calls the existing `notifier` tool with an Obsidian deep link:

```python
notifier.send(
    title=f"[blocked] {task.title}",
    body=task.status_reason or "需要你回应",
    deep_link=f"obsidian://open?vault=cc-assistant&file=blocked/{task.id}-{task.slug}.md"
)
```

WeChat enterprise bot delivers the message. Tapping the link opens Obsidian directly to the task file.

Pre-conditions:
- Obsidian mobile is installed and the `obsidian://` URL scheme is registered (automatic on install).
- The vault is named `cc-assistant` exactly, matching the Sync configuration.

### User Response Path

In Obsidian, the user can:

1. **Edit frontmatter via the Properties UI** — change `who: claude` to hand back to the AI, or change `priority`, or fill `instructions`.
2. **Append to the conversation section** — insert `### [Human] YYYY-MM-DD HH:MM` followed by content. A Templater snippet can speed this up but is not required.
3. **Set `intent`** — change `intent: null` to `intent: resume / approve / reject / pause` and save. The daemon picks up the change and performs the corresponding column move (see Task Model section).

Setting `intent` is the recommended path for column transitions. It is one property edit instead of a multi-step "Move file" gesture, and matches the architecture's "file is the single source of truth" principle.

### Notifier Secrets

The WeChat webhook URL lives **outside the vault**, at `<repo-root>/.env` (loaded via `python-dotenv` per existing config conventions). Keeping secrets out of `tasks/` ensures they never sync to mobile via Obsidian Sync regardless of the user's exclude-list configuration. `.env` is already in repository `.gitignore`.

## Out of Scope

| Feature | Why deferred |
|---|---|
| Explainer landing page | Already deferred per memory `plan5b_ui_reference.md`; static HTML, decoupled from this plan |
| `skills/rules.md` editing UI | Place `rules.md` in the vault (or symlink). Obsidian edits it natively. No custom UI |
| Strikethrough subtask edit display from reference video | Not natively supported by Obsidian; manual `~~old~~ new` works but is not structured. v1 does not enforce |
| Image attachments in task files | `_attachments/` + Obsidian Sync handle this without daemon changes. `![[xxx.png]]` works out of the box |
| Multi-vault support | One vault = one cc-assistant instance. Defer until a second project demands it |
| Auto-start of desktop Obsidian | User configures via Windows startup items; not the daemon's responsibility |

### Future Backlog (Not Plan 5b)

- Bases v2 views: by `who`, by `parent` for subtask trees
- Templater one-click "Approve / Reject / Resume" buttons (if `intent` UX proves slow)
- Mobile dataview dashboard (weekly throughput, average cycle time)
- Standalone explainer page (docs-only PR)

## Retired Code (Plan 5b execution removes)

```
src/dispatcher/sync.py             # git auto-commit/push/pull
tests/test_sync.py                 # corresponding tests
src/web/                           # never implemented; if scaffolded, delete
```

## Implementation Estimate

| Module | Estimate |
|---|---|
| Task model + parser/writer + tests | 0.5 day |
| Watcher ignore patterns + `intent` handling | 0.5 day |
| Templates + `.gitignore` + vault initialization script | 0.5 day |
| Bases configuration + manual desktop/mobile testing | 1 day |
| Notifier deep link + tests | 0.25 day |
| `sync.py` retirement + test removal | 0.25 day |
| LLM context wiring (`measure`, `why`, `source_files`) | 0.5 day |
| End-to-end manual test (phone <-> desktop <-> daemon) | 0.5 day |
| **Total** | **~4 days** |

Compare against original Plan 5b (FastAPI path): ~10+ days. Net saving ~60%.

## Open Questions / Risks

- **Obsidian Sync billing tier.** User must verify whether their current subscription covers a second vault. Standard tier historically permits one vault; Plus tier is needed for multiple. If upgrading is undesirable, fall back to Syncthing for the cc-assistant vault while keeping Obsidian Sync on the personal vault.
- **Bases syntax stability.** Bases is a 2025 feature; minor syntax changes between Obsidian versions are possible. Implementation aligns to docs at execution time.
- **Desktop Obsidian uptime.** The architecture requires desktop Obsidian to be running for Sync to land bytes on disk. Acceptable for a single-developer setup; would not scale to a server-side deployment.
